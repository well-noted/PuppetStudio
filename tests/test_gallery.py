from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from studio.core import new,store,save
from studio.gallery import catalog,record

class GalleryTests(unittest.TestCase):
    def test_lists_published_outputs_and_opt_in_completed_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store(root,new());base=root/'renders/solo';(base/'clips').mkdir(parents=True)
            for rel in ['clips/speech.mp4','clips/speech_preview.mp4','combined.mp4','group_topic.mp4','clip_hash/clip.mp4','other_hash/part_000.mp4','unfinished/clip.mp4','joined.tmp.mp4']:
                f=base/rel;f.parent.mkdir(exist_ok=True);f.write_bytes(b'fixture video')
            archive=base/'clip_hash/clip.mp4';save(archive.with_suffix('.done.json'),{'signature':'complete'})
            published=base/'clips/speech.mp4';record(published,title='Test title',preview=False,duration=12.5)
            items=catalog(root);self.assertEqual(len(items),4)
            self.assertEqual({x['kind'] for x in items},{'clip','preview','combined','group'})
            self.assertEqual(next(x for x in items if x['path'].endswith('speech.mp4'))['duration'],12.5)
            history=catalog(root,True);self.assertEqual(len(history),5);self.assertEqual(sum(x['archived'] for x in history),1)
    def test_stale_metadata_is_not_presented_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store(root,new());f=root/'renders/solo/clips/test.mp4';f.parent.mkdir(parents=True);f.write_bytes(b'a');record(f,duration=12)
            f.write_bytes(b'new bytes');self.assertIsNone(catalog(root)[0]['duration'])
    def test_symlink_outside_project_is_excluded(self):
        with tempfile.TemporaryDirectory() as folder,tempfile.TemporaryDirectory() as other:
            root=Path(folder);store(root,new());base=root/'renders/solo';base.mkdir(parents=True);outside=Path(other)/'private.mp4';outside.write_bytes(b'private')
            try:(base/'escape.mp4').symlink_to(outside)
            except OSError:self.skipTest('Symlinks unavailable')
            self.assertEqual(catalog(root),[])

if __name__=='__main__':unittest.main()
