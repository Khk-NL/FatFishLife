"""Prepare short same-character reference voices; keep URIs only on this PC."""
import argparse
import hashlib
from html import unescape
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fatfish_video.renderer import _resolve_tool
from configure_local_services import read_env


def run(args):
    args.output.mkdir(parents=True,exist_ok=True)
    text=args.source_html.read_text(encoding='utf-8')
    matches=list(re.finditer(r'<div class="voice-data-item"([^>]*)>',text))
    voices={}
    for i,m in enumerate(matches):
        attrs={k:unescape(v) for k,v in re.findall(r'([\w-]+)="([^"]*)"',m.group(1))}
        block=text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]
        cn=re.search(r'<div[^>]+class="voice-item-detail"[^>]+data-kind-name="中文"[^>]*>(.*?)</div>',block,re.S)
        if cn:
            spoken=unescape(re.sub('<[^>]+>',' ',cn.group(1))).strip()
            voices[int(attrs['data-voice-index'])]=(attrs['data-voice-filename'].split('.')[0].lower(),spoken)
    key=read_env(args.env_file)['FATFISH_SILICONFLOW_KEY']
    ffmpeg,ffprobe=str(_resolve_tool('ffmpeg')),str(_resolve_tool('ffprobe'))
    profiles={};report={'registered':[],'failed':[]}
    for mode,indices in {'neutral':[34,36,1,3],'happy':[28,29,30,19],'soft':[10,42,1,34]}.items():
        saved=args.output/(mode+'.json')
        if saved.exists():
            profiles[mode]=json.loads(saved.read_text())['uri'];report['registered'].append(mode);continue
        clips=[];words=[];seconds=0
        for number in indices:
            name,transcript=voices[number];path=args.output/(name+'.mp3')
            url='https://torappu.prts.wiki/assets/audio/voice_cn/char_103_angel/'+name+'.mp3'
            if not path.exists():
                with urllib.request.urlopen(url,timeout=25) as response:path.write_bytes(response.read())
            duration=float(subprocess.check_output([ffprobe,'-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)]))
            if seconds+duration>25:continue
            clips.append(path);words.append(transcript);seconds+=duration
            if seconds>=8:break
        if seconds<5:raise ValueError('Insufficient aligned reference audio')
        reference=args.output/(mode+'-reference.wav')
        command=[ffmpeg,'-nostdin','-v','error','-y']
        for path in clips:command+=['-i',str(path)]
        command+=['-filter_complex',''.join(f'[{i}:a]' for i in range(len(clips)))+f'concat=n={len(clips)}:v=0:a=1[out]',
                  '-map','[out]','-ar','24000','-ac','1',str(reference)]
        subprocess.run(command,check=True,capture_output=True,timeout=30)
        boundary=uuid.uuid4().hex;parts=[]
        fields={'model':'FunAudioLLM/CosyVoice2-0.5B','customName':'exusiai_'+mode+'_'+hashlib.sha256(reference.read_bytes()).hexdigest()[:8],'text':'。'.join(words)}
        for k,v in fields.items():parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),reference.read_bytes(),f'\r\n--{boundary}--\r\n'.encode()]
        req=urllib.request.Request('https://api.siliconflow.cn/v1/uploads/audio/voice',data=b''.join(parts),headers={'Authorization':'Bearer '+key,'Content-Type':'multipart/form-data; boundary='+boundary})
        try:
            with urllib.request.urlopen(req,timeout=60) as response:data=json.load(response)
            uri=data.get('uri') or data.get('data',{}).get('uri')
            if not uri:raise ValueError('No registered voice URI')
            saved.write_text(json.dumps({'uri':uri,'duration':round(seconds,3),'source':'PRTS 能天使 中文语音','indices':[p.stem for p in clips]}),encoding='utf-8')
            profiles[mode]=uri;report['registered'].append(mode)
        except Exception as exc:report['failed'].append({'mode':mode,'error':type(exc).__name__})
    (args.output/'profiles.json').write_text(json.dumps(profiles),encoding='utf-8')
    (args.output/'result.json').write_text(json.dumps(report),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',type=Path,default=Path('D:/Code/Apps/.env'))
    p.add_argument('--source-html',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'outputs/voice-profiles')
    run(p.parse_args())
