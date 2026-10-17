"""Integration: Bash preserves session state despite failed commands."""
import os
import shutil
import subprocess
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder,new_completion_token,wrap_bash_command

class PersistentSessionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'POSIX Bash required')
    def test_state_and_exit_code_after_error(self):
        token=new_completion_token()
        commands=['export SHELLDECK_TEST_VALUE=ok', 'false',
                  'printf "%s\n" "$SHELLDECK_TEST_VALUE"', 'cd /tmp', 'pwd']
        script=''.join(wrap_bash_command(c,token) for c in commands)
        p=subprocess.run([shutil.which('bash'),'--noprofile','--norc'],input=script,
                         text=True,capture_output=True,timeout=5)
        self.assertEqual(p.returncode,0)
        dec=BashCompletionDecoder(token)
        text,status=dec.feed(p.stdout)
        self.assertEqual(status,[0,1,0,0,0])
        self.assertIn('ok',text)
        self.assertIn('/tmp',text)
        self.assertNotIn('job control',p.stderr.lower())
