"""Conservative timestamp validation; never sort or globally retime source speech."""
import math

def normalize(data,duration):
    duration=float(duration)
    if not math.isfinite(duration) or duration<=0:raise ValueError('Media duration must be finite and positive')
    warnings=[]
    def interval(item,kind,index,last,allow_zero=False):
        try:start,end=float(item['start']),float(item['end'])
        except (KeyError,TypeError,ValueError):raise ValueError(f'{kind}[{index}] has missing/non-numeric start or end') from None
        detail=f'{kind}[{index}]: start={start!r}, end={end!r}; media duration={duration:.3f}s; previous start={last!r}'
        if not all(math.isfinite(x) for x in [start,end]) or start<-.05 or end>duration+.25 or end<start or start<last-.05:
            raise ValueError(detail+'. Expected ordered, finite timestamps inside the recording.')
        fixed_start=max(0,min(duration,start));fixed_end=max(0,min(duration,end))
        if (fixed_start,fixed_end)!=(start,end):warnings.append(detail+'; clipped small boundary rounding to media bounds.')
        if fixed_start>=fixed_end and not allow_zero:raise ValueError(detail+'. Segment has no positive duration.')
        return fixed_start,fixed_end
    segments=[];last=-1
    for i,item in enumerate(data.get('segments',[])):
        text=item.get('text','').strip()
        if not text:continue
        start,end=interval(item,'segments',i,last,allow_zero=True);last=start
        segments.append({'start':start,'end':end,'text':text})
    timed=[i for i,s in enumerate(segments) if s['end']>s['start']]
    owners={i:[(i,segments[i]['text'])] for i in timed}
    import bisect
    for i,s in enumerate(segments):
        if i in owners:continue
        at=bisect.bisect_left(timed,i);neighbors=timed[max(0,at-1):at+1]
        def distance(j):return min(abs(s['start']-segments[j]['start']),abs(s['start']-segments[j]['end']))
        nearest=min(neighbors,key=distance) if neighbors else None
        if nearest is None or distance(nearest)>.25:
            raise ValueError(f'segments[{i}]: start={s["start"]}, end={s["end"]}; zero duration has no adjacent timed segment. Raw text retained for review.')
        owners[nearest].append((i,s['text']))
        warnings.append(f'segments[{i}] has zero duration; text merged into adjacent timed segment {nearest}, without shifting speech.')
    segments=[{**segments[i],'text':' '.join(text for _,text in sorted(owners[i]))} for i in timed]
    raw=data.get('words') or [w for s in data.get('segments',[]) for w in s.get('words',[])]
    words=[];last=-1
    for i,item in enumerate(raw):
        text=item.get('word',item.get('text','')).strip()
        if not text:continue
        start,end=interval(item,'words',i,last,allow_zero=True);last=start
        words.append({'start':start,'end':end,'word':text})
    # Whisper can assign an instantaneous timestamp to a token. Preserve its
    # text with an adjacent timed token, without inventing extra speech duration.
    positive=[i for i,w in enumerate(words) if w['end']>w['start']]
    owners={i:[(i,words[i]['word'])] for i in positive};fallback=False
    for i,w in enumerate(words):
        if i in owners:continue
        at=bisect.bisect_left(positive,i);neighbors=positive[max(0,at-1):at+1]
        def distance(j):return min(abs(w['start']-words[j]['start']),abs(w['start']-words[j]['end']))
        nearest=min(neighbors,key=distance) if neighbors else None
        if nearest is None or distance(nearest)>.25:
            fallback=True;break
        owners[nearest].append((i,w['word']))
        warnings.append(f'words[{i}] has zero duration at {w["start"]:.3f}s; text merged with adjacent timed word {nearest}.')
    if fallback:
        if not segments:raise ValueError('Word timestamps have unsupported zero-duration tokens and no segment timing for fallback.')
        words=[];warnings.append('Zero-duration words lack adjacent timing; using original segment captions instead. No speech times shifted.')
    else:
        words=[{**words[i],'word':' '.join(text for _,text in sorted(owners[i]))} for i in positive]
    if not segments and words:segments=[{'start':words[0]['start'],'end':max(w['end'] for w in words),'text':' '.join(w['word'] for w in words)}]
    if not segments:raise ValueError('Transcript is empty')
    return {'segments':segments,'words':words,'language':data.get('language',''),'warnings':warnings}
