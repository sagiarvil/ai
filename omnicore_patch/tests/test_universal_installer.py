import tempfile
import unittest
from pathlib import Path
from universal_installer import classify, parse_github


class InstallerStaticTests(unittest.TestCase):
    def test_github_url(self):
        self.assertEqual(parse_github('https://github.com/a/b')[0:2], ('a', 'b'))
        for url in ['http://github.com/a/b', 'https://evil.com/a/b', 'https://github.com/a/b?x=1',
                    'https://github.com/a/b/../../etc', 'https://github.com/a/b;echo',
                    'https://github.com/a/b/c']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_github(url)

    def test_classify(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(classify(root), 'unsupported')
            (root / 'package.json').write_text('{}')
            self.assertEqual(classify(root), 'node')
            (root / 'requirements.txt').write_text('')
            self.assertEqual(classify(root), 'python')

if __name__ == '__main__':
    unittest.main()
