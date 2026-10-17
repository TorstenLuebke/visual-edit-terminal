"""A durable noninteractive Bash pipe must preserve mutable shell state."""
import os
import shutil
import subprocess
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder, wrap_bash_command, new_completion_token

class PersistentBashTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix' and shutil.which('bash'), 'POSIX bash required')
    def test_source_export_cd_and_failure_exit_codes(self):
        token=new_completion_token()
        p=subprocess.Popen([shutil.which('bash'),'--noprofile','--norc'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            script='export SDECK_VALUE=example\ncd /tmp\nsource /dev/stdin\n'
            # source /dev/stdin would read the marker as script content; this
            # test explicitly demonstrates why source must remain excluded.
            self.assertIn('source', script)
            self.assertTrue(p.stdin is not None)
            p.stdin.write(wrap_bash_command('export SDECK_VALUE=example',token).encode())
            p.stdin.write(wrap_bash_command('cd /tmp',token).encode())
            p.stdin.write(wrap_bash_command('printf "%s:%s\\n" "$SDECK_VALUE" "$PWD"',token).encode())
            p.stdin.write(wrap_bash_command('false',token).encode())
            p.stdin.close()
            stdout=p.stdout.read().decode('utf-8','replace')
            stderr=p.stderr.read().decode('utf-8','replace')
            self.assertEqual(p.wait(timeout=5),0)
            dec=BashCompletionDecoder(token)
            visible,codes=dec.feed(stdout)
            visible+=dec.finish()
            self.assertEqual(codes,[0,0,0,1])
            self.assertIn('example:/tmp',visible)
            self.assertNotIn('job control',stderr.lower())
        finally:
            if p.poll() is None: p.kill();p.wait()
            for stream in (p.stdin,p.stdout,p.stderr):
                if stream is not None and not stream.closed:stream.close()
