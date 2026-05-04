import requests as req
import csv
from bs4 import BeautifulSoup
import html


BASE_URL = "https://highload.ru"

links = [
    "https://highload.ru/moscow/2025/abstracts",
    "https://highload.ru/spb/2026/abstracts"
]

def parse_abstracts(url: str, out: str):
    resp = req.get(url=url)
    if resp.status_code != 200:
        exit("Ошибка подключения")
    
    html_resp = resp.text
    
    soup = BeautifulSoup(html_resp, "html.parser")
    
    f = open(out, mode="w", newline='', encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=[
            "author",
            "author_avatar",
            "company",
            "title",
            "date",
            "stack",
            "description",
            "link",
    ])
    writer.writeheader()
    
    thesis_list = soup.find("div", class_="thesis__list")
    for thesis in thesis_list.find_all("div", recursive=False):
        for report in thesis.find_all("div", recursive=False):
            stacks = []
            authors = {}
            
            title = report.find("h2", class_="thesis__item-title").find("a", class_="thesis__item-title-link")
            link = BASE_URL + title.get("href")
            
            if report.find("div", class_="thesis__tags") is not None:
                for stack in report.find("div", class_="thesis__tags").find_all("div", recursive=False):
                    stacks.append(stack.text)

            for author in report.find("div", class_="thesis__authors").find_all("div", class_="thesis__author", recursive=False):
                company = author.find("p", class_="thesis__author-company").text
                name = author.find("a", class_="thesis__author-name").text
                avatar = BASE_URL + author.find("a", class_="thesis__author-img").get("style")[22:-1]
                authors[name] = {
                    "company": company,
                    "avatar": avatar
                }
            try:
                date_text = report.find("a", class_="thesis__item-schedule-text").text
                date = date_text[:date_text.find(",")]
            except:
                date = ""
            description = report.find("div", class_="thesis__text").get_text()
            
            for name, d_author in authors.items():
                writer.writerow(
                    {
                        "author": name,
                        "author_avatar": d_author["avatar"],
                        "company": d_author["company"],
                        "title": title.text,
                        "date": date,
                        "stack": ", ".join(stacks),
                        "description": description,
                        "link": link,
                    }
                )
    f.close()        
            
            



parse_abstracts(links[0], "out.csv")