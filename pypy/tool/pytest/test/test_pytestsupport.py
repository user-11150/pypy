from pypy.interpreter.error import OperationError
from pypy.tool.pytest.appsupport import AppExceptionInfo
import py
import pypy
conftestpath = py.path.local(pypy.__file__).dirpath("conftest.py")

pytest_plugins = "pytester"

def app_test_exception():
    try:
        raise AssertionError("42")
    except AssertionError:
        pass
    else:
        raise AssertionError("app level AssertionError mixup!")

def app_test_exception_with_message():
    try:
        assert 0, "Failed"
    except AssertionError as e:
        assert e.msg == "Failed"


def test_appexecinfo(space):
    try:
        space.appexec([], "(): raise ValueError")
    except OperationError as e:
        appex = AppExceptionInfo(space, e)
    else:
        py.test.fail("did not raise!")
    assert appex.exconly().find('ValueError') != -1
    assert appex.exconly(tryshort=True).find('ValueError') != -1
    assert appex.errisinstance(ValueError)
    assert not appex.errisinstance(RuntimeError)
    class A:
        pass
    assert not appex.errisinstance(A)


class AppTestWithWrappedInterplevelAttributes:
    def setup_class(cls):
        space = cls.space
        cls.w_some1 = space.wrap(42)

    def setup_method(self, meth):
        self.w_some2 = self.space.wrap(23)

    def test_values_arrive(self):
        assert self.some1 == 42
        assert self.some2 == 23

    def test_values_arrive2(self):
        assert self.some1 == 42

    def w_compute(self, x):
        return x + 2

    def test_equal(self):
        assert self.compute(3) == 5


def test_app_test_blow(testdir):
    conftestpath.copy(testdir.tmpdir)
    sorter = testdir.inline_runsource("""class AppTestBlow:
    def test_one(self): exec('blow')
    """)

    reports = sorter.getreports("pytest_runtest_logreport")
    setup, ev, teardown = reports
    assert ev.failed
    assert setup.passed
    assert teardown.passed
    assert 'NameError' in ev.longrepr.reprcrash.message
    assert 'blow' in ev.longrepr.reprcrash.message
