"""Catalogue project outputs without scanning face caches or speech chunks."""
from pathlib import Path
from .core import load,path,read

def catalog(root,history=False):
    root=Path(root).resolve();p=load(root);names={x['id']:x['name'] for x in p['productions']};clips={x['id']:x for x in p['clips']};base=root/'renders';result=[]
    if not base.is_dir():return result
    for folder in base.iterdir():
        if not folder.is_dir():continue
        files=[*folder.glob('*.mp4'),*(folder/'clips').glob('*.mp4')]
        if history:files.extend(folder.glob('*/clip.mp4'))
        for f in files:
            try:
                rel=f.relative_to(root).as_posix();safe=path(root,rel)
                if not safe.is_file():continue
                stat=safe.stat()
                if not stat.st_size or f.name.endswith(('.tmp.mp4','.partial.mp4')):continue
                archived=f.name=='clip.mp4' and f.parent!=folder/'clips'
                if archived and not f.with_suffix('.done.json').is_file():continue
                key=f.stem;preview=key.endswith('_preview');plain=key[:-8] if preview else key
                kind='version' if archived else 'combined' if plain=='combined' else 'group' if plain.startswith('group_') else 'preview' if preview else 'clip'
                clip=clips.get(plain);title=clip['title'] if clip else ('Combined production' if kind=='combined' else plain.removeprefix('group_').replace('_',' '))
                metadata={}
                record=f.with_suffix('.render.json')
                if record.is_file():
                    try:
                        metadata=read(record)
                        if metadata.get('size_bytes')!=stat.st_size or metadata.get('modified_ns')!=stat.st_mtime_ns:metadata={}
                    except (ValueError,OSError):pass
                title=metadata.get('title') or title
                if archived:
                    clip=clips.get(metadata.get('clip_id'));title=metadata.get('title') or (clip['title'] if clip else f.parent.name)
                result.append({'path':rel,'production_id':folder.name,'production_name':names.get(folder.name,folder.name),'title':title,'kind':kind,'preview':metadata.get('preview',preview),'archived':archived,'size_bytes':stat.st_size,'modified':stat.st_mtime,'duration':metadata.get('duration')})
            except (ValueError,OSError):continue
    return sorted(result,key=lambda x:x['modified'],reverse=True)

def record(file,**metadata):
    f=Path(file);stat=f.stat()
    from .core import save
    save(f.with_suffix('.render.json'),{**metadata,'size_bytes':stat.st_size,'modified_ns':stat.st_mtime_ns})
