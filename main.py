import argparse
import smtplib
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib import parse, request
from urllib.error import HTTPError

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader


class EmailSender:

    sent_terms_fpath = Path("./sent_terms.txt")

    def __init__(self, address, password, start_term="Python", n_terms_per_retreive=5):
        self.address = address
        self.password = password

        self.start_term = start_term
        self.n_terms_per_retreive = n_terms_per_retreive

    def crawl(self, term):
        base_url = "http://www.howtopronounce.cc"
        target_url = base_url + "/" + parse.quote(term).lower()
        try:
            response = request.urlopen(target_url)
        except HTTPError as e:
            print(f"[{e.code}] {str(e)} (target URL: {target_url}")
        else:
            with response:
                soup = BeautifulSoup(response, "html.parser")
            cards = soup.find_all("div", class_="card")
            (
                pronunciation_card,
                description_card,
                related_terms_card,
                most_searched_terms_card,
            ) = cards

            current_term = soup.find("input").get("value")
            audios_urls = [
                (base_url + btn.get("data-src")) for btn in pronunciation_card.find_all("button", class_="audio")
            ]
            audios_upvotes = [
                int(btn.get("data-like-count")) for btn in pronunciation_card.find_all("button", class_="like")
            ]
            description = description_card.find(class_="card-body").text.strip()
            related_terms = [parse.unquote(a.get("href").lstrip("/")) for a in related_terms_card.find_all("a")]
            most_searched_terms = [
                parse.unquote(a.get("href").lstrip("/")) for a in most_searched_terms_card.find_all("a")
            ]
            return {
                "url": target_url,
                "name": current_term,
                "description": description,
                "audios": sorted(
                    [{"url": url, "upvotes": upvotes} for url, upvotes in zip(audios_urls, audios_upvotes)],
                    key=lambda audio: audio["upvotes"],
                    reverse=True,
                ),
                "related_terms": list(dict.fromkeys(most_searched_terms + related_terms).keys()),
            }

    def retreive(self):
        if not self.sent_terms_fpath.exists():
            term_info = self.crawl(self.start_term)
            assert term_info is not None, "Please launch the sender with a valid <start_term>."
            terms_info = {self.start_term: term_info}
            for term in term_info["related_terms"]:
                if term not in terms_info:
                    term_info = self.crawl(term)
                    if term_info is not None:
                        terms_info[term] = term_info
                    if len(terms_info) == self.n_terms_per_retreive:
                        return terms_info

        with open(self.sent_terms_fpath, "r") as f:
            sent_terms = dict.fromkeys((sent_term.strip().lower() for sent_term in f.readlines())).keys()
        terms_info = dict()
        start = time.time()
        for sent_term in sent_terms:
            sent_term_info = self.crawl(sent_term)
            if sent_term_info is None:
                print(f"Warning: subpage /{sent_term} has been removed from website.")
                continue
            for term in sent_term_info["related_terms"]:
                if term not in sent_terms and term not in terms_info:
                    term_info = self.crawl(term)
                    if term_info is not None:
                        terms_info[term] = term_info
                if len(terms_info) == self.n_terms_per_retreive or (time.time() - start) > 7200:
                    return terms_info

    def send(self, terms_info, address):
        if len(terms_info) == 0:
            print("No new terms found.")
            return None

        email = EmailMessage()
        email["Subject"] = f"Daily HowToPronounce ({', '.join([term['name'] for term in terms_info.values()])})"
        email["From"] = self.address
        email["To"] = address

        env = Environment(loader=FileSystemLoader("./templates"))
        template = env.get_template("email.html")
        html_content = template.render(terms=terms_info.values())
        email.set_content(html_content, subtype="html")

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(self.address, self.password)
            server.send_message(email)

        self.update_sent_terms(terms_info)

    def update_sent_terms(self, terms_info):
        with open(self.sent_terms_fpath, "a") as f:
            for term in terms_info.values():
                f.write(term["name"] + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("Send daily HowToPronounce emails")
    parser.add_argument("--sender-email", type=str, required=True, help="Sender email address")
    parser.add_argument("--sender-password", type=str, required=True, help="Sender email password")
    parser.add_argument("--receiver-email", type=str, required=True, help="Receiver email address")
    args = parser.parse_args()

    sender = EmailSender(args.sender_email, args.sender_password)
    terms_info = sender.retreive()
    sender.send(terms_info, args.receiver_email)
