import py, os, sys
from .support import setup_make


currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("templatesDict.so"))

def setup_module(mod):
    setup_make("templatesDict.so")

class AppTestTEMPLATES:
    spaceconfig = dict(usemodules=['_cppyy', '_rawffi', 'itertools'])

    def setup_class(cls):
        cls.w_test_dct  = cls.space.newtext(test_dct)
        cls.w_datatypes = cls.space.appexec([], """():
            import ctypes, _cppyy
            _cppyy._post_import_startup()
            return ctypes.CDLL(%r, ctypes.RTLD_GLOBAL)""" % (test_dct, ))

    def test01_template_member_functions(self):
        """Template member functions lookup and calls"""

        import _cppyy

        m = _cppyy.gbl.MyTemplatedMethodClass()

      # pre-instantiated
        assert m.get_size['char']()   == m.get_char_size()
        assert m.get_size[int]()      == m.get_int_size()

      # specialized
        assert m.get_size[long]()     == m.get_long_size()

      # auto-instantiation
        assert m.get_size[float]()    == m.get_float_size()
        assert m.get_size['double']() == m.get_double_size()
        assert m.get_size['MyTemplatedMethodClass']() == m.get_self_size()

      # auto through typedef
        assert m.get_size['MyTMCTypedef_t']() == m.get_self_size()

    def test02_non_type_template_args(self):
        """Use of non-types as template arguments"""

        import _cppyy

        _cppyy.gbl.gInterpreter.Declare("template<int i> int nt_templ_args() { return i; };")

        assert _cppyy.gbl.nt_templ_args[1]()   == 1
        assert _cppyy.gbl.nt_templ_args[256]() == 256

    def test03_templated_function(self):
        """Templated global and static functions lookup and calls"""

        import _cppyy

        # TODO: the following only works if something else has already
        # loaded the headers associated with this template
        ggs = _cppyy.gbl.global_get_size
        assert ggs['char']() == 1

        gsf = _cppyy.gbl.global_some_foo

        assert gsf[int](3) == 42
        assert gsf(3)      == 42
        assert gsf(3.)     == 42

        gsb = _cppyy.gbl.global_some_bar

        assert gsb(3)            == 13
        assert gsb['double'](3.) == 13

        # TODO: the following only works in a namespace
        nsgsb = _cppyy.gbl.SomeNS.some_bar

        assert nsgsb[3]
        assert nsgsb[3]() == 3

        # TODO: add some static template method

    def test04_variadic_function(self):
        """Call a variadic function"""

        import _cppyy

        s = _cppyy.gbl.std.ostringstream()
        #s << '('
        #_cppyy.gbl.SomeNS.tuplify(s, 1, 4., "aap")
        #assert s.str() == '(1, 4, aap)

    def test05_variadic_overload(self):
        """Call an overloaded variadic function"""

        import _cppyy

        assert _cppyy.gbl.isSomeInt(3.)        == False
        assert _cppyy.gbl.isSomeInt(1)         == True
        assert _cppyy.gbl.isSomeInt()          == False
        assert _cppyy.gbl.isSomeInt(1, 2, 3)   == False

    def test06_variadic_sfinae(self):
        """Attribute testing through SFINAE"""

        import _cppyy
        Obj1             = _cppyy.gbl.AttrTesting.Obj1
        Obj2             = _cppyy.gbl.AttrTesting.Obj2
        has_var1         = _cppyy.gbl.AttrTesting.has_var1
        call_has_var1    = _cppyy.gbl.AttrTesting.call_has_var1

        move = _cppyy.gbl.std.move

        assert has_var1(Obj1()) == hasattr(Obj1(), 'var1')
        assert has_var1(Obj2()) == hasattr(Obj2(), 'var1')
        assert has_var1(3)      == hasattr(3,      'var1')
        assert has_var1("aap")  == hasattr("aap",  'var1')

        assert call_has_var1(move(Obj1())) == True
        assert call_has_var1(move(Obj2())) == False

    def test07_type_deduction(self):
        """Traits/type deduction"""

        import _cppyy
        Obj1                  = _cppyy.gbl.AttrTesting.Obj1
        Obj2                  = _cppyy.gbl.AttrTesting.Obj2
        select_template_arg   = _cppyy.gbl.AttrTesting.has_var1

       #assert select_template_arg[0, Obj1, Obj2].argument == Obj1
        assert select_template_arg[1, Obj1, Obj2].argument == Obj2
        raises(TypeError, select_template_arg.__getitem__, 2, Obj1, Obj2)

        # TODO, this doesn't work for builtin types as the 'argument'
        # typedef will not resolve to a class
        #assert select_template_arg[1, int, float].argument == float

    def test08_using_of_static_data(self):
        """Derived class using static data of base"""

        import _cppyy

      # TODO: the following should live in templates.h, but currently fails
      # in TClass::GetListOfMethods()
        _cppyy.gbl.gInterpreter.Declare("""
        template <typename T> struct BaseClassWithStatic {
            static T const ref_value;
        };

        template <typename T>
        T const BaseClassWithStatic<T>::ref_value = 42;

        template <typename T>
        struct DerivedClassUsingStatic : public BaseClassWithStatic<T> {
            using BaseClassWithStatic<T>::ref_value;

            explicit DerivedClassUsingStatic(T x) : BaseClassWithStatic<T>() {
                m_value = x > ref_value ? ref_value : x;
            }

            T m_value;
        };""")


      # TODO: the ref_value property is inaccessible (offset == -1)
      # assert cppyy.gbl.BaseClassWithStatic["size_t"].ref_value == 42

        b1 = _cppyy.gbl.DerivedClassUsingStatic["size_t"](  0)
        b2 = _cppyy.gbl.DerivedClassUsingStatic["size_t"](100)

      # assert b1.ref_value == 42
        assert b1.m_value   ==  0

      # assert b2.ref_value == 42
        assert b2.m_value   == 42
