import argparse
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def main():
    parser = argparse.ArgumentParser(description='Run backend tests in an empty working directory.')
    parser.add_argument('suite', nargs='?', choices=('test', 'tests'))
    parser.add_argument('--shuffle-seed', type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    original_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='taosync-tests-') as tmp:
        try:
            os.chdir(tmp)
            suite = unittest.TestSuite()
            for directory in (args.suite,) if args.suite else ('test', 'tests'):
                suite.addTests(unittest.TestLoader().discover(str(root / directory)))
            if not suite.countTestCases():
                parser.error('No tests were discovered.')
            if args.shuffle_seed is not None:
                cases = list(test_cases(suite))
                random.Random(args.shuffle_seed).shuffle(cases)
                suite = unittest.TestSuite(cases)
                print(f'Shuffle seed: {args.shuffle_seed}', flush=True)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            artifacts = sorted(path.name for path in Path(tmp).iterdir())
            if artifacts:
                print(f'Tests leaked files into the working directory: {artifacts}', file=sys.stderr)
            return int(not result.wasSuccessful() or bool(artifacts))
        finally:
            os.chdir(original_cwd)


if __name__ == '__main__':
    sys.exit(main())
