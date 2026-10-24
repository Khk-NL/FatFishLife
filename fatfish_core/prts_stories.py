"""Discover actual story pages instead of treating event announcements as plot."""
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack=[]; self.rows=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='tr': self.stack.append({'text':[],'links':[]})
        if tag=='a' and self.stack:
            title=unescape(attrs.get('title',''));href=attrs.get('href','')
            if title.endswith(('/BEG','/END','/NBT')) and href.startswith('/w/'):
                self.stack[-1]['links'].append({'title':title,'url':'https://prts.wiki'+href})
    def handle_data(self,data):
        if self.stack and data.strip(): self.stack[-1]['text'].append(data.strip())
    def handle_endtag(self,tag):
        if tag=='tr' and self.stack:
            row=self.stack.pop()
            if row['links']: self.rows.append(row)


def chapter_catalog(html: str, names) -> dict:
    parser=Rows();parser.feed(html);result={}
    for row in parser.rows:
        labels=set(row['text'])
        matches=[name for name in names if name in labels]
        if len(matches)!=1:continue
        name=matches[0];bank=result.setdefault(name,{})
        for item in row['links']:bank[item['title']]=item
    return {name:list(items.values()) for name,items in result.items()}


def room_sections(html: str) -> dict:
    anchors=list(re.finditer(r'<p id="([^"]+)" style="margin:0;padding:0;">',html))
    result={}
    for index,m in enumerate(anchors):
        block=html[m.end():anchors[index+1].start() if index+1<len(anchors) else len(html)]
        block=re.sub(r'<(script|style)\b.*?</\1>','',block,flags=re.S|re.I)
        block=re.sub(r'<br\s*/?>|</(?:p|div|li|tr|td|th)>','\n',block,flags=re.I)
        text=unescape(re.sub('<[^>]+>',' ',block));lines=[]
        for line in text.splitlines():
            line=' '.join(line.split())
            if line and (not lines or lines[-1]!=line):lines.append(line)
        result[unescape(m.group(1))]='\n'.join(lines)
    return result


def fetch_page(title: str, cache: Path) -> dict:
    cache.mkdir(parents=True,exist_ok=True)
    import hashlib
    target=cache/(hashlib.sha256(title.encode()).hexdigest()+'.json')
    if target.exists():return json.loads(target.read_text(encoding='utf-8'))
    params={'action':'parse','page':title,'prop':'text','format':'json','formatversion':2,'disablelimitreport':1}
    req=urllib.request.Request('https://prts.wiki/api.php?'+urllib.parse.urlencode(params),headers={'User-Agent':'FatFishLife/1.0 (source-backed personal knowledge)'})
    with urllib.request.urlopen(req,timeout=35) as response:obj=json.load(response)
    if 'parse' not in obj:raise ValueError('PRTS page missing')
    result={'title':obj['parse']['title'],'html':obj['parse']['text'],'revision':obj['parse'].get('revid')}
    target.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return result
