"""Ground event summaries and plot pointers in PRTS story indexes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fatfish_core.prts_stories import chapter_catalog,room_sections,fetch_page


def run(args):
    cache=ROOT/'.web-data/prts-source'
    room=fetch_page('情报处理室',cache);index=fetch_page('剧情一览',cache)
    sections=room_sections(room['html'])
    aliases={"玛莉娅临光":"玛莉娅·临光", "理想城长夏狂欢季":"理想城：长夏狂欢季", "火蓝之心/黑曜石节":"火蓝之心"}
    target=ROOT/'docs/knowledge/prts/07-活动梗概.md'
    text=target.read_text(encoding='utf-8');blocks=re.findall(r'(?ms)^## (.+?)\n(.*?)(?=^## |\Z)',text)
    names=list(dict.fromkeys([name for name,_ in blocks]+list(sections)))
    catalog=chapter_catalog(index['html'],names)
    for alias,canonical in aliases.items():
        if canonical in catalog:
            catalog[alias]=catalog[canonical]
    if len(catalog)<50:
        raise ValueError('Story index parsing incomplete; existing documents preserved')
    directory=ROOT/'docs/knowledge/prts';(directory/'story_catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf-8')
    cfg=json.loads((args.astrbot/'data/cmd_config.json').read_text(encoding='utf-8-sig'))
    src=next(s for s in cfg['provider_sources'] if s['id']=='deepseek');key=src['key'][0] if isinstance(src['key'],list) else src['key']
    out=ROOT/'outputs/activity-grounded';out.mkdir(parents=True,exist_ok=True)
    results={};errors=[]
    report={'catalog_events':len(catalog),'room_events':len(sections),'completed':0,'failed':0}
    def one(item):
        name,source=item
        if name not in catalog:return None
        digest=hashlib.sha256(source.encode()).hexdigest();saved=out/(hashlib.sha256(name.encode()).hexdigest()+'.json')
        if saved.exists():
            value=json.loads(saved.read_text(encoding='utf-8'))
            if value.get('digest')==digest:return name,value
        # All stage synopsis material is used; retain beginning/end for long events.
        material=source if len(source)<=10000 else source[:5500]+'\n[中段略]\n'+source[-4500:]
        prompt=('仅根据下面的游戏内剧情回顾概要，用自己的话写事实提要。不要复述原句，不要凭记忆补角色、结局或因果。'
                '不要把公告、关卡玩法和营销文案当剧情。summary不超过150字，details不超过400字、含3至5个关键转折。'
                'characters里的人名必须原样出现在素材中。没有明确支持就写资料不足。'
                '仅输出JSON：{"characters":[],"summary":"","details":""}。\n活动：'+name+'\n素材：'+material)
        body=json.dumps({'model':'deepseek-flash','messages':[{'role':'user','content':prompt}],
                         'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},'max_tokens':1800,'temperature':.1}).encode()
        request=urllib.request.Request(src['api_base'].rstrip('/')+'/chat/completions',data=body,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        with urllib.request.urlopen(request,timeout=90) as response:r=json.load(response)
        from fatfish_story.client import _loads_json_object
        value=_loads_json_object(r['choices'][0]['message']['content'])
        value['characters']=[n for n in value.get('characters',[]) if isinstance(n,str) and n in source]
        if not value.get('summary') or not value.get('details'):raise ValueError('Incomplete story summary')
        value.update(digest=digest,source='https://prts.wiki/w/情报处理室#'+name,chapters=catalog[name])
        saved.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return name,value
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(one,item):item[0] for item in sections.items() if item[0] in catalog}
        from concurrent.futures import as_completed
        for f in as_completed(futures):
            try:
                result=f.result()
                if result:results[result[0]]=result[1];report['completed']+=1
            except Exception as exc:errors.append({'event':futures[f],'error':type(exc).__name__});report['failed']+=1
            (out/'progress.json').write_text(json.dumps(report),encoding='utf-8')
    for name,old in blocks:
        canonical=aliases.get(name,name)
        if canonical not in results:continue
        v=results[canonical];new='\n- 登场：'+('、'.join(v['characters']) or '资料不足')+'\n- 梗概：'+v['summary'][:220]+'\n- 来源：'+v['source']+'\n\n'
        text=text.replace('## '+name+'\n'+old,'## '+name+'\n'+new,1)
    target.write_text(text,encoding='utf-8')
    lines=['# 活动剧情事实提要','依据游戏内剧情回顾概要整理；不是全文，也不补写概要没有的细节。完整章节由剧情索引按需查证。','']
    for name in sections:
        if name not in results:continue
        v=results[name];lines.extend(['## '+name,'',v['details'][:650],'','来源：'+v['source'],
                                    '章节索引：'+', '.join(c['title'] for c in v['chapters']),''])
    (directory/'08-活动剧情事实提要.md').write_text('\n'.join(lines),encoding='utf-8')
    report.update(errors=errors,unmatched_titles=[name for name,_ in blocks if name not in catalog])
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ['errors','unmatched_titles']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--astrbot',type=Path,required=True);run(p.parse_args())
