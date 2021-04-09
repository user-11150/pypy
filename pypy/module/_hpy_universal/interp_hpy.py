from rpython.rtyper.lltypesystem import lltype, rffi
from rpython.rlib.rdynload import dlopen, dlsym, DLOpenError

from pypy.interpreter.gateway import unwrap_spec
from pypy.interpreter.error import raise_import_error
from pypy.interpreter.error import OperationError, oefmt

from pypy.module._hpy_universal import llapi, handles
from pypy.module._hpy_universal.state import State
from pypy.module._hpy_universal.apiset import API
from pypy.module._hpy_universal.llapi import BASE_DIR

# these imports have side effects, as they call @API.func()
from pypy.module._hpy_universal import (
    interp_err,
    interp_long,
    interp_module,
    interp_number,
    interp_unicode,
    interp_float,
    interp_bytes,
    interp_call,
    interp_dict,
    interp_list,
    interp_tuple,
    interp_builder,
    interp_object,
    interp_cpy_compat,
    interp_type,
    interp_tracker,
    )

def init_hpy_module(space, w_mod):
    """
    Initialize _hpy_universal. This is called by moduledef.Module.__init__
    """
    state = space.fromcache(State)
    state.setup()
    h_debug_mod = llapi.HPyInit__debug(state.ctx)
    w_debug_mod = handles.consume(space, h_debug_mod)
    w_mod.setdictvalue(space, '_debug', w_debug_mod)

def load_version():
    # eval the content of _vendored/hpy/devel/version.py without importing it
    version_py = BASE_DIR.join('version.py').read()
    d = {}
    exec(version_py, d)
    return d['__version__'], d['__git_revision__']
HPY_VERSION, HPY_GIT_REV = load_version()


def create_hpy_module(space, name, origin, lib, debug, initfunc_ptr):
    state = space.fromcache(State)
    initfunc_ptr = rffi.cast(llapi.HPyInitFunc, initfunc_ptr)
    if debug:
        ctx = llapi.hpy_debug_get_ctx(state.ctx)
    else:
        ctx = state.ctx
    h_module = initfunc_ptr(ctx)
    if not h_module:
        raise oefmt(space.w_SystemError,
            "initialization of %s failed without raising an exception",
            name)
    if debug:
        h_module = llapi.hpy_debug_unwrap_handle(h_module)
    return handles.consume(space, h_module)

def descr_load_from_spec(space, w_spec):
    name = space.text_w(space.getattr(w_spec, space.newtext("name")))
    origin = space.fsencode_w(space.getattr(w_spec, space.newtext("origin")))
    return descr_load(space, name, origin)

@unwrap_spec(name='text', path='fsencode', debug=bool)
def descr_load(space, name, path, debug=False):
    try:
        with rffi.scoped_str2charp(path) as ll_libname:
            lib = dlopen(ll_libname, space.sys.dlopenflags)
    except DLOpenError as e:
        w_path = space.newfilename(path)
        raise raise_import_error(space,
            space.newfilename(e.msg), space.newtext(name), w_path)

    basename = name.split('.')[-1]
    init_name = 'HPyInit_' + basename
    try:
        initptr = dlsym(lib, init_name)
    except KeyError:
        msg = b"function %s not found in library %s" % (
            init_name, space.utf8_w(space.newfilename(path)))
        w_path = space.newfilename(path)
        raise raise_import_error(
            space, space.newtext(msg), space.newtext(name), w_path)
    return create_hpy_module(space, name, path, lib, debug, initptr)

def descr_get_version(space):
    w_ver = space.newtext(HPY_VERSION)
    w_git_rev = space.newtext(HPY_GIT_REV)
    return space.newtuple([w_ver, w_git_rev])

@API.func("HPy HPy_Dup(HPyContext ctx, HPy h)")
def HPy_Dup(space, ctx, h):
    return handles.dup(space, h)

@API.func("void HPy_Close(HPyContext ctx, HPy h)")
def HPy_Close(space, ctx, h):
    handles.close(space, h)
