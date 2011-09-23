# -*- coding: utf-8 -*-

from unittest import *
import unittest.case
import unittest.main
import unittest.result
import unittest.runner
import unittest.suite
import time
import sys

orig_stdout = sys.stdout

class TextBenchResult(unittest.runner.TextTestResult):
    """Collects results including benchmarking time"""
    def startTest(self, test):
        super(TextBenchResult, self).startTest(test)
        self.start_time = time.time()
        if hasattr(self, "setup_time"):
            del self.setup_time

    def stopTest(self, test):
        """Called when the given test has been run"""
        self.end_time = time.time()
        if hasattr(test, "setup_time"):
            start_time = self.setup_time = test.setup_time
            self.stream.writeln("Setup duration %0.2f" % (self.setup_time - self.start_time))
        else:
            start_time = self.start_time
        self.stream.writeln("Duration %0.2f" % (self.end_time - start_time))
        super(TextBenchResult, self).stopTest(test)

class BenchCase(unittest.case.TestCase):
    BENCH_REPEATS = 1000
    def setup_complete(self):
        self.setup_time = time.time()

class BenchSuite(unittest.suite.TestSuite):
    pass

class TextBenchRunner(unittest.runner.TextTestRunner):
    resultclass = TextBenchResult

def main(*args, **kwargs):
    kwargs.setdefault('testRunner', TextBenchRunner)
    kwargs.setdefault('verbosity', 2)
    unittest.main(*args, **kwargs)

