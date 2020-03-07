"""
Implementation of a part of the standard Python opcodes.

The rest, dealing with variables in optimized ways, is in nestedscope.py.
"""

from rpython.rlib import jit, rstackovf, rstring
from rpython.rlib.debug import check_nonneg
from rpython.rlib.objectmodel import (
    we_are_translated, always_inline, dont_inline, not_rpython)
from rpython.rlib.rarithmetic import r_uint, intmask
from rpython.tool.sourcetools import func_with_new_name

from pypy.interpreter import (
    gateway, function, eval, pyframe, pytraceback, pycode
)
from pypy.interpreter.baseobjspace import W_Root
from pypy.interpreter.error import OperationError, oefmt
from pypy.interpreter.nestedscope import Cell
from pypy.interpreter.pycode import PyCode, BytecodeCorruption
from pypy.tool.stdlib_opcode import bytecode_spec

CANNOT_CATCH_MSG = ("catching classes that don't inherit from BaseException "
                    "is not allowed in 3.x")

@not_rpython
def unaryoperation(operationname):
    def opimpl(self, *ignored):
        operation = getattr(self.space, operationname)
        w_1 = self.popvalue()
        w_result = operation(w_1)
        self.pushvalue(w_result)
    opimpl.unaryop = operationname

    return func_with_new_name(opimpl, "opcode_impl_for_%s" % operationname)

@not_rpython
def binaryoperation(operationname):
    def opimpl(self, *ignored):
        operation = getattr(self.space, operationname)
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        w_result = operation(w_1, w_2)
        self.pushvalue(w_result)
    opimpl.binop = operationname

    return func_with_new_name(opimpl, "opcode_impl_for_%s" % operationname)


opcodedesc = bytecode_spec.opcodedesc
HAVE_ARGUMENT = bytecode_spec.HAVE_ARGUMENT

class __extend__(pyframe.PyFrame):
    """A PyFrame that knows about interpretation of standard Python opcodes
    minus the ones related to nested scopes."""

    ### opcode dispatch ###

    def dispatch(self, pycode, next_instr, ec):
        # For the sequel, force 'next_instr' to be unsigned for performance
        next_instr = r_uint(next_instr)
        co_code = pycode.co_code
        try:
            while True:
                assert next_instr & 1 == 0
                next_instr = self.handle_bytecode(co_code, next_instr, ec)
        except ExitFrame:
            return self.popvalue()

    def handle_bytecode(self, co_code, next_instr, ec):
        try:
            next_instr = self.dispatch_bytecode(co_code, next_instr, ec)
        except OperationError as operr:
            operr.record_context(self.space, ec)
            next_instr = self.handle_operation_error(ec, operr)
        except RaiseWithExplicitTraceback as e:
            next_instr = self.handle_operation_error(ec, e.operr,
                                                     attach_tb=False)
        except KeyboardInterrupt:
            next_instr = self.handle_asynchronous_error(ec,
                self.space.w_KeyboardInterrupt)
        except MemoryError:
            next_instr = self.handle_asynchronous_error(ec,
                self.space.w_MemoryError)
        except rstackovf.StackOverflow as e:
            # Note that this case catches AttributeError!
            rstackovf.check_stack_overflow()
            next_instr = self.handle_asynchronous_error(ec,
                self.space.w_RecursionError,
                self.space.newtext("maximum recursion depth exceeded"))
        return next_instr

    def handle_asynchronous_error(self, ec, w_type, w_value=None):
        # catch asynchronous exceptions and turn them
        # into OperationErrors
        if w_value is None:
            w_value = self.space.w_None
        operr = OperationError(w_type, w_value)
        return self.handle_operation_error(ec, operr)

    def handle_generator_error(self, operr):
        # for generator.py
        ec = self.space.getexecutioncontext()
        return self.handle_operation_error(ec, operr)

    def handle_operation_error(self, ec, operr, attach_tb=True):
        if attach_tb:
            if 1:
                # xxx this is a hack.  It allows bytecode_trace() to
                # call a signal handler which raises, and catch the
                # raised exception immediately.  See test_alarm_raise in
                # pypy/module/signal/test/test_signal.py.  Without the
                # next four lines, if an external call (like
                # socket.accept()) is interrupted by a signal, it raises
                # an exception carrying EINTR which arrives here,
                # entering the next "except" block -- but the signal
                # handler is then called on the next call to
                # dispatch_bytecode(), causing the real exception to be
                # raised after the exception handler block was popped.
                try:
                    trace = self.get_w_f_trace()
                    if trace is not None:
                        self.getorcreatedebug().w_f_trace = None
                    try:
                        ec.bytecode_trace_after_exception(self)
                    finally:
                        if trace is not None:
                            self.getorcreatedebug().w_f_trace = trace
                except OperationError as e:
                    operr = e
            pytraceback.record_application_traceback(
                self.space, operr, self, self.last_instr)
            ec.exception_trace(self, operr)

        block = self.unrollstack(SApplicationException.kind)
        if block is None:
            # no handler found for the OperationError
            if we_are_translated():
                raise operr
            else:
                # try to preserve the CPython-level traceback
                import sys
                tb = sys.exc_info()[2]
                raise OperationError, operr, tb
        else:
            unroller = SApplicationException(operr)
            next_instr = block.handle(self, unroller)
            return next_instr

    def call_contextmanager_exit_function(self, w_func, w_typ, w_val, w_tb):
        return self.space.call_function(w_func, w_typ, w_val, w_tb)

    @jit.unroll_safe
    def dispatch_bytecode(self, co_code, next_instr, ec):
        while True:
            assert next_instr & 1 == 0
            self.last_instr = intmask(next_instr)
            if jit.we_are_jitted():
                ec.bytecode_only_trace(self)
            else:
                ec.bytecode_trace(self)
            next_instr = r_uint(self.last_instr)
            assert next_instr & 1 == 0
            opcode = ord(co_code[next_instr])
            oparg = ord(co_code[next_instr + 1])
            next_instr += 2

            # note: the structure of the code here is such that it makes
            # (after translation) a big "if/elif" chain, which is then
            # turned into a switch().

            while opcode == opcodedesc.EXTENDED_ARG.index:
                opcode = ord(co_code[next_instr])
                arg = ord(co_code[next_instr + 1])
                if opcode < HAVE_ARGUMENT:
                    raise BytecodeCorruption
                next_instr += 2
                oparg = (oparg * 256) | arg

            if opcode == opcodedesc.RETURN_VALUE.index:
                if not self.blockstack_non_empty():
                    self.frame_finished_execution = True  # for generators
                    raise Return
                w_returnvalue = self.popvalue()
                block = self.unrollstack(SReturnValue.kind)
                if block is None:
                    self.pushvalue(w_returnvalue)
                    raise Return
                else:
                    unroller = SReturnValue(w_returnvalue)
                    next_instr = block.handle(self, unroller)
                    return next_instr    # now inside a 'finally' block
            elif opcode == opcodedesc.END_FINALLY.index:
                unroller = self.end_finally()
                if isinstance(unroller, SuspendedUnroller):
                    # go on unrolling the stack
                    block = self.unrollstack(unroller.kind)
                    if block is None:
                        w_result = unroller.nomoreblocks()
                        self.pushvalue(w_result)
                        raise Return
                    else:
                        next_instr = block.handle(self, unroller)
                return next_instr
            elif opcode == opcodedesc.JUMP_ABSOLUTE.index:
                return self.jump_absolute(oparg, ec)
            elif opcode == opcodedesc.BREAK_LOOP.index:
                next_instr = self.BREAK_LOOP(oparg, next_instr)
            elif opcode == opcodedesc.CONTINUE_LOOP.index:
                return self.CONTINUE_LOOP(oparg, next_instr)
            elif opcode == opcodedesc.FOR_ITER.index:
                next_instr = self.FOR_ITER(oparg, next_instr)
            elif opcode == opcodedesc.JUMP_FORWARD.index:
                next_instr = self.JUMP_FORWARD(oparg, next_instr)
            elif opcode == opcodedesc.JUMP_IF_FALSE_OR_POP.index:
                next_instr = self.JUMP_IF_FALSE_OR_POP(oparg, next_instr)
            elif opcode == opcodedesc.JUMP_IF_TRUE_OR_POP.index:
                next_instr = self.JUMP_IF_TRUE_OR_POP(oparg, next_instr)
            elif opcode == opcodedesc.POP_JUMP_IF_FALSE.index:
                next_instr = self.POP_JUMP_IF_FALSE(oparg, next_instr)
            elif opcode == opcodedesc.POP_JUMP_IF_TRUE.index:
                next_instr = self.POP_JUMP_IF_TRUE(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_ADD.index:
                self.BINARY_ADD(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_AND.index:
                self.BINARY_AND(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_FLOOR_DIVIDE.index:
                self.BINARY_FLOOR_DIVIDE(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_MATRIX_MULTIPLY.index:
                self.BINARY_MATRIX_MULTIPLY(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_LSHIFT.index:
                self.BINARY_LSHIFT(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_MODULO.index:
                self.BINARY_MODULO(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_MULTIPLY.index:
                self.BINARY_MULTIPLY(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_OR.index:
                self.BINARY_OR(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_POWER.index:
                self.BINARY_POWER(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_RSHIFT.index:
                self.BINARY_RSHIFT(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_SUBSCR.index:
                self.BINARY_SUBSCR(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_SUBTRACT.index:
                self.BINARY_SUBTRACT(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_TRUE_DIVIDE.index:
                self.BINARY_TRUE_DIVIDE(oparg, next_instr)
            elif opcode == opcodedesc.BINARY_XOR.index:
                self.BINARY_XOR(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_CONST_KEY_MAP.index:
                self.BUILD_CONST_KEY_MAP(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_LIST.index:
                self.BUILD_LIST(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_LIST_FROM_ARG.index:
                self.BUILD_LIST_FROM_ARG(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_LIST_UNPACK.index:
                self.BUILD_LIST_UNPACK(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_MAP.index:
                self.BUILD_MAP(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_MAP_UNPACK.index:
                self.BUILD_MAP_UNPACK(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_MAP_UNPACK_WITH_CALL.index:
                self.BUILD_MAP_UNPACK_WITH_CALL(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_SET.index:
                self.BUILD_SET(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_SET_UNPACK.index:
                self.BUILD_SET_UNPACK(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_SLICE.index:
                self.BUILD_SLICE(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_TUPLE.index:
                self.BUILD_TUPLE(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_TUPLE_UNPACK.index:
                self.BUILD_TUPLE_UNPACK(oparg, next_instr)
            elif opcode == opcodedesc.CALL_FUNCTION.index:
                self.CALL_FUNCTION(oparg, next_instr)
            elif opcode == opcodedesc.CALL_FUNCTION_KW.index:
                self.CALL_FUNCTION_KW(oparg, next_instr)
            elif opcode == opcodedesc.CALL_FUNCTION_EX.index:
                self.CALL_FUNCTION_EX(oparg, next_instr)
            elif opcode == opcodedesc.CALL_METHOD.index:
                self.CALL_METHOD(oparg, next_instr)
            elif opcode == opcodedesc.CALL_METHOD_KW.index:
                self.CALL_METHOD_KW(oparg, next_instr)
            elif opcode == opcodedesc.COMPARE_OP.index:
                self.COMPARE_OP(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_ATTR.index:
                self.DELETE_ATTR(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_DEREF.index:
                self.DELETE_DEREF(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_FAST.index:
                self.DELETE_FAST(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_ANNOTATIONS.index:
                self.SETUP_ANNOTATIONS(oparg, next_instr)
            elif opcode == opcodedesc.STORE_ANNOTATION.index:
                self.STORE_ANNOTATION(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_GLOBAL.index:
                self.DELETE_GLOBAL(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_NAME.index:
                self.DELETE_NAME(oparg, next_instr)
            elif opcode == opcodedesc.DELETE_SUBSCR.index:
                self.DELETE_SUBSCR(oparg, next_instr)
            elif opcode == opcodedesc.DUP_TOP.index:
                self.DUP_TOP(oparg, next_instr)
            elif opcode == opcodedesc.DUP_TOP_TWO.index:
                self.DUP_TOP_TWO(oparg, next_instr)
            elif opcode == opcodedesc.GET_ITER.index:
                self.GET_ITER(oparg, next_instr)
            elif opcode == opcodedesc.IMPORT_FROM.index:
                self.IMPORT_FROM(oparg, next_instr)
            elif opcode == opcodedesc.IMPORT_NAME.index:
                self.IMPORT_NAME(oparg, next_instr)
            elif opcode == opcodedesc.IMPORT_STAR.index:
                self.IMPORT_STAR(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_ADD.index:
                self.INPLACE_ADD(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_AND.index:
                self.INPLACE_AND(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_FLOOR_DIVIDE.index:
                self.INPLACE_FLOOR_DIVIDE(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_LSHIFT.index:
                self.INPLACE_LSHIFT(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_MATRIX_MULTIPLY.index:
                self.INPLACE_MATRIX_MULTIPLY(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_MODULO.index:
                self.INPLACE_MODULO(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_MULTIPLY.index:
                self.INPLACE_MULTIPLY(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_OR.index:
                self.INPLACE_OR(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_POWER.index:
                self.INPLACE_POWER(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_RSHIFT.index:
                self.INPLACE_RSHIFT(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_SUBTRACT.index:
                self.INPLACE_SUBTRACT(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_TRUE_DIVIDE.index:
                self.INPLACE_TRUE_DIVIDE(oparg, next_instr)
            elif opcode == opcodedesc.INPLACE_XOR.index:
                self.INPLACE_XOR(oparg, next_instr)
            elif opcode == opcodedesc.LIST_APPEND.index:
                self.LIST_APPEND(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_ATTR.index:
                self.LOAD_ATTR(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_BUILD_CLASS.index:
                self.LOAD_BUILD_CLASS(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_CLOSURE.index:
                self.LOAD_CLOSURE(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_CONST.index:
                self.LOAD_CONST(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_DEREF.index:
                self.LOAD_DEREF(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_CLASSDEREF.index:
                self.LOAD_CLASSDEREF(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_FAST.index:
                self.LOAD_FAST(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_GLOBAL.index:
                self.LOAD_GLOBAL(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_NAME.index:
                self.LOAD_NAME(oparg, next_instr)
            elif opcode == opcodedesc.LOOKUP_METHOD.index:
                self.LOOKUP_METHOD(oparg, next_instr)
            elif opcode == opcodedesc.MAKE_FUNCTION.index:
                self.MAKE_FUNCTION(oparg, next_instr)
            elif opcode == opcodedesc.MAP_ADD.index:
                self.MAP_ADD(oparg, next_instr)
            elif opcode == opcodedesc.NOP.index:
                self.NOP(oparg, next_instr)
            elif opcode == opcodedesc.POP_BLOCK.index:
                self.POP_BLOCK(oparg, next_instr)
            elif opcode == opcodedesc.POP_EXCEPT.index:
                self.POP_EXCEPT(oparg, next_instr)
            elif opcode == opcodedesc.POP_TOP.index:
                self.POP_TOP(oparg, next_instr)
            elif opcode == opcodedesc.PRINT_EXPR.index:
                self.PRINT_EXPR(oparg, next_instr)
            elif opcode == opcodedesc.RAISE_VARARGS.index:
                self.RAISE_VARARGS(oparg, next_instr)
            elif opcode == opcodedesc.ROT_THREE.index:
                self.ROT_THREE(oparg, next_instr)
            elif opcode == opcodedesc.ROT_TWO.index:
                self.ROT_TWO(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_EXCEPT.index:
                self.SETUP_EXCEPT(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_FINALLY.index:
                self.SETUP_FINALLY(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_LOOP.index:
                self.SETUP_LOOP(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_WITH.index:
                self.SETUP_WITH(oparg, next_instr)
            elif opcode == opcodedesc.SET_ADD.index:
                self.SET_ADD(oparg, next_instr)
            elif opcode == opcodedesc.STORE_ATTR.index:
                self.STORE_ATTR(oparg, next_instr)
            elif opcode == opcodedesc.STORE_DEREF.index:
                self.STORE_DEREF(oparg, next_instr)
            elif opcode == opcodedesc.STORE_FAST.index:
                self.STORE_FAST(oparg, next_instr)
            elif opcode == opcodedesc.STORE_GLOBAL.index:
                self.STORE_GLOBAL(oparg, next_instr)
            elif opcode == opcodedesc.STORE_NAME.index:
                self.STORE_NAME(oparg, next_instr)
            elif opcode == opcodedesc.STORE_SUBSCR.index:
                self.STORE_SUBSCR(oparg, next_instr)
            elif opcode == opcodedesc.UNARY_INVERT.index:
                self.UNARY_INVERT(oparg, next_instr)
            elif opcode == opcodedesc.UNARY_NEGATIVE.index:
                self.UNARY_NEGATIVE(oparg, next_instr)
            elif opcode == opcodedesc.UNARY_NOT.index:
                self.UNARY_NOT(oparg, next_instr)
            elif opcode == opcodedesc.UNARY_POSITIVE.index:
                self.UNARY_POSITIVE(oparg, next_instr)
            elif opcode == opcodedesc.UNPACK_EX.index:
                self.UNPACK_EX(oparg, next_instr)
            elif opcode == opcodedesc.UNPACK_SEQUENCE.index:
                self.UNPACK_SEQUENCE(oparg, next_instr)
            elif opcode == opcodedesc.WITH_CLEANUP_START.index:
                self.WITH_CLEANUP_START(oparg, next_instr)
            elif opcode == opcodedesc.WITH_CLEANUP_FINISH.index:
                self.WITH_CLEANUP_FINISH(oparg, next_instr)
            elif opcode == opcodedesc.YIELD_VALUE.index:
                self.YIELD_VALUE(oparg, next_instr)
            elif opcode == opcodedesc.YIELD_FROM.index:
                self.YIELD_FROM(oparg, next_instr)
            elif opcode == opcodedesc.GET_YIELD_FROM_ITER.index:
                self.GET_YIELD_FROM_ITER(oparg, next_instr)
            elif opcode == opcodedesc.GET_AWAITABLE.index:
                self.GET_AWAITABLE(oparg, next_instr)
            elif opcode == opcodedesc.SETUP_ASYNC_WITH.index:
                self.SETUP_ASYNC_WITH(oparg, next_instr)
            elif opcode == opcodedesc.BEFORE_ASYNC_WITH.index:
                self.BEFORE_ASYNC_WITH(oparg, next_instr)
            elif opcode == opcodedesc.GET_AITER.index:
                self.GET_AITER(oparg, next_instr)
            elif opcode == opcodedesc.GET_ANEXT.index:
                self.GET_ANEXT(oparg, next_instr)
            elif opcode == opcodedesc.FORMAT_VALUE.index:
                self.FORMAT_VALUE(oparg, next_instr)
            elif opcode == opcodedesc.BUILD_STRING.index:
                self.BUILD_STRING(oparg, next_instr)
            elif opcode == opcodedesc.LOAD_REVDB_VAR.index:
                self.LOAD_REVDB_VAR(oparg, next_instr)
            else:
                self.MISSING_OPCODE(oparg, next_instr)

            if jit.we_are_jitted():
                return next_instr

    @jit.unroll_safe
    def unrollstack(self, unroller_kind):
        while self.blockstack_non_empty():
            block = self.pop_block()
            if (block.handling_mask & unroller_kind) != 0:
                return block
            block.cleanupstack(self)
        self.frame_finished_execution = True  # for generators
        return None

    def unrollstack_and_jump(self, unroller):
        block = self.unrollstack(unroller.kind)
        if block is None:
            raise BytecodeCorruption("misplaced bytecode - should not return")
        return block.handle(self, unroller)

    ### accessor functions ###

    def getlocalvarname(self, index):
        return self.getcode().co_varnames[index]

    def getconstant_w(self, index):
        return self.getcode().co_consts_w[index]

    def getname_u(self, index):
        return self.space.text_w(self.getname_w(index))

    def getname_w(self, index):
        return self.getcode().co_names_w[index]


    ################################################################
    ##  Implementation of the "operational" opcodes
    ##  See also nestedscope.py for the rest.
    ##

    def NOP(self, oparg, next_instr):
        # annotation-time check: if it fails, it means that the decoding
        # of oparg failed to produce an integer which is annotated as non-neg
        check_nonneg(oparg)

    @always_inline
    def LOAD_FAST(self, varindex, next_instr):
        # access a local variable directly
        w_value = self.locals_cells_stack_w[varindex]
        if w_value is None:
            self._load_fast_failed(varindex)
        self.pushvalue(w_value)

    @dont_inline
    def _load_fast_failed(self, varindex):
        varname = self.getlocalvarname(varindex)
        raise oefmt(self.space.w_UnboundLocalError,
                    "local variable '%s' referenced before assignment",
                    varname)

    def LOAD_CONST(self, constindex, next_instr):
        w_const = self.getconstant_w(constindex)
        self.pushvalue(w_const)

    def STORE_FAST(self, varindex, next_instr):
        w_newvalue = self.popvalue()
        assert w_newvalue is not None
        self.locals_cells_stack_w[varindex] = w_newvalue

    def getfreevarname(self, index):
        freevarnames = self.pycode.co_cellvars + self.pycode.co_freevars
        return freevarnames[index]

    def iscellvar(self, index):
        # is the variable given by index a cell or a free var?
        return index < len(self.pycode.co_cellvars)

    def LOAD_DEREF(self, varindex, next_instr):
        # nested scopes: access a variable through its cell object
        cell = self._getcell(varindex)
        try:
            w_value = cell.get()
        except ValueError:
            self.raise_exc_unbound(varindex)
        else:
            self.pushvalue(w_value)

    def LOAD_CLASSDEREF(self, varindex, next_instr):
        # like LOAD_DEREF but used in class bodies
        space = self.space
        i = varindex - len(self.pycode.co_cellvars)
        assert i >= 0
        name = self.pycode.co_freevars[i]
        w_value = space.finditem(self.debugdata.w_locals, space.newtext(name))
        if w_value is None:
            self.LOAD_DEREF(varindex, next_instr)
        else:
            self.pushvalue(w_value)

    def STORE_DEREF(self, varindex, next_instr):
        # nested scopes: access a variable through its cell object
        w_newvalue = self.popvalue()
        cell = self._getcell(varindex)
        cell.set(w_newvalue)

    def DELETE_DEREF(self, varindex, next_instr):
        cell = self._getcell(varindex)
        try:
            cell.get()
        except ValueError:
            self.raise_exc_unbound(varindex)
        else:
            cell.set(None)

    def raise_exc_unbound(self, varindex):
        varname = self.getfreevarname(varindex)
        if self.iscellvar(varindex):
            raise oefmt(self.space.w_UnboundLocalError,
                        "local variable '%s' referenced before assignment",
                        varname)
        else:
            raise oefmt(self.space.w_NameError,
                        "free variable '%s' referenced before assignment"
                        " in enclosing scope", varname)

    def LOAD_CLOSURE(self, varindex, next_instr):
        # nested scopes: access the cell object
        w_value = self._getcell(varindex)
        self.pushvalue(w_value)

    def POP_TOP(self, oparg, next_instr):
        self.popvalue()

    def ROT_TWO(self, oparg, next_instr):
        w_1 = self.popvalue()
        w_2 = self.popvalue()
        self.pushvalue(w_1)
        self.pushvalue(w_2)

    def ROT_THREE(self, oparg, next_instr):
        w_1 = self.popvalue()
        w_2 = self.popvalue()
        w_3 = self.popvalue()
        self.pushvalue(w_1)
        self.pushvalue(w_3)
        self.pushvalue(w_2)

    def DUP_TOP(self, oparg, next_instr):
        w_1 = self.peekvalue()
        self.pushvalue(w_1)

    def DUP_TOP_TWO(self, oparg, next_instr):
        self.dupvalues(2)

    def DUP_TOPX(self, itemcount, next_instr):
        assert 1 <= itemcount <= 5, "limitation of the current interpreter"
        self.dupvalues(itemcount)

    UNARY_POSITIVE = unaryoperation("pos")
    UNARY_NEGATIVE = unaryoperation("neg")
    UNARY_NOT      = unaryoperation("not_")
    UNARY_CONVERT  = unaryoperation("repr")
    UNARY_INVERT   = unaryoperation("invert")

    def BINARY_POWER(self, oparg, next_instr):
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        w_result = self.space.pow(w_1, w_2, self.space.w_None)
        self.pushvalue(w_result)

    BINARY_MULTIPLY = binaryoperation("mul")
    BINARY_TRUE_DIVIDE  = binaryoperation("truediv")
    BINARY_FLOOR_DIVIDE = binaryoperation("floordiv")
    BINARY_DIVIDE       = binaryoperation("div")
    # XXX BINARY_DIVIDE must fall back to BINARY_TRUE_DIVIDE with -Qnew
    BINARY_MODULO       = binaryoperation("mod")
    BINARY_MATRIX_MULTIPLY = binaryoperation("matmul")
    BINARY_ADD      = binaryoperation("add")
    BINARY_SUBTRACT = binaryoperation("sub")
    BINARY_SUBSCR   = binaryoperation("getitem")
    BINARY_LSHIFT   = binaryoperation("lshift")
    BINARY_RSHIFT   = binaryoperation("rshift")
    BINARY_AND = binaryoperation("and_")
    BINARY_XOR = binaryoperation("xor")
    BINARY_OR  = binaryoperation("or_")

    def INPLACE_POWER(self, oparg, next_instr):
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        w_result = self.space.inplace_pow(w_1, w_2)
        self.pushvalue(w_result)

    INPLACE_MULTIPLY = binaryoperation("inplace_mul")
    INPLACE_TRUE_DIVIDE  = binaryoperation("inplace_truediv")
    INPLACE_FLOOR_DIVIDE = binaryoperation("inplace_floordiv")
    INPLACE_DIVIDE       = binaryoperation("inplace_div")
    # XXX INPLACE_DIVIDE must fall back to INPLACE_TRUE_DIVIDE with -Qnew
    INPLACE_MODULO       = binaryoperation("inplace_mod")
    INPLACE_MATRIX_MULTIPLY = binaryoperation("inplace_matmul")
    INPLACE_ADD      = binaryoperation("inplace_add")
    INPLACE_SUBTRACT = binaryoperation("inplace_sub")
    INPLACE_LSHIFT   = binaryoperation("inplace_lshift")
    INPLACE_RSHIFT   = binaryoperation("inplace_rshift")
    INPLACE_AND = binaryoperation("inplace_and")
    INPLACE_XOR = binaryoperation("inplace_xor")
    INPLACE_OR  = binaryoperation("inplace_or")

    def STORE_SUBSCR(self, oparg, next_instr):
        "obj[subscr] = newvalue"
        w_subscr = self.popvalue()
        w_obj = self.popvalue()
        w_newvalue = self.popvalue()
        self.space.setitem(w_obj, w_subscr, w_newvalue)

    def DELETE_SUBSCR(self, oparg, next_instr):
        "del obj[subscr]"
        w_subscr = self.popvalue()
        w_obj = self.popvalue()
        self.space.delitem(w_obj, w_subscr)

    def PRINT_EXPR(self, oparg, next_instr):
        w_expr = self.popvalue()
        print_expr(self.space, w_expr)

    def PRINT_ITEM_TO(self, oparg, next_instr):
        w_stream = self.popvalue()
        w_item = self.popvalue()
        if self.space.is_w(w_stream, self.space.w_None):
            w_stream = sys_stdout(self.space)   # grumble grumble special cases
        print_item_to(self.space, self._printable_object(w_item), w_stream)

    def PRINT_ITEM(self, oparg, next_instr):
        w_item = self.popvalue()
        print_item(self.space, self._printable_object(w_item))

    def _printable_object(self, w_obj):
        space = self.space
        if not space.isinstance_w(w_obj, space.w_unicode):
            w_obj = space.str(w_obj)
        return w_obj

    def PRINT_NEWLINE_TO(self, oparg, next_instr):
        w_stream = self.popvalue()
        if self.space.is_w(w_stream, self.space.w_None):
            w_stream = sys_stdout(self.space)   # grumble grumble special cases
        print_newline_to(self.space, w_stream)

    def PRINT_NEWLINE(self, oparg, next_instr):
        print_newline(self.space)

    def BREAK_LOOP(self, oparg, next_instr):
        return self.unrollstack_and_jump(SBreakLoop.singleton)

    def CONTINUE_LOOP(self, startofloop, next_instr):
        unroller = SContinueLoop(startofloop)
        return self.unrollstack_and_jump(unroller)

    def RAISE_VARARGS(self, nbargs, next_instr):
        space = self.space
        if nbargs > 2:
            raise BytecodeCorruption("bad RAISE_VARARGS oparg")
        if nbargs == 0:
            if not self.hide():
                last_operr = self.space.getexecutioncontext().sys_exc_info()
            else:
                last_operr = self.getorcreatedebug().hidden_operationerr
            if last_operr is None:
                raise oefmt(space.w_RuntimeError,
                            "No active exception to reraise")
            # re-raise, no new traceback obj will be attached
            raise RaiseWithExplicitTraceback(last_operr)
        if nbargs == 2:
            w_cause = self.popvalue()
            if space.exception_is_valid_obj_as_class_w(w_cause):
                w_cause = space.call_function(w_cause)
        else:
            w_cause = None
        w_value = self.popvalue()
        if space.exception_is_valid_obj_as_class_w(w_value):
            w_type = w_value
            w_value = space.call_function(w_type)
        else:
            w_type = space.type(w_value)
        operror = OperationError(w_type, w_value)
        operror.normalize_exception(space)
        operror.set_cause(space, w_cause)
        tb = space.getattr(w_value, space.newtext('__traceback__'))
        if not space.is_w(tb, space.w_None):
            operror.set_traceback(tb)
        raise operror

    def LOAD_LOCALS(self, oparg, next_instr):
        self.pushvalue(self.getorcreatedebug().w_locals)

    def exec_(self, w_prog, w_globals, w_locals):
        """The builtins.exec function."""
        space = self.space
        ec = space.getexecutioncontext()
        flags = ec.compiler.getcodeflags(self.pycode)

        if space.isinstance_w(w_prog, space.gettypeobject(PyCode.typedef)):
            code = space.interp_w(PyCode, w_prog)
        else:
            from pypy.interpreter.astcompiler import consts
            flags |= consts.PyCF_SOURCE_IS_UTF8
            source, flags = source_as_str(space, w_prog, 'exec',
                                          "string, bytes or code", flags)
            code = ec.compiler.compile(source, "<string>", 'exec', flags)

        w_globals, w_locals = ensure_ns(space, w_globals, w_locals, 'exec',
                                        self)
        space.call_method(w_globals, 'setdefault', space.newtext('__builtins__'),
                          self.get_builtin())

        code.exec_code(space, w_globals, w_locals)

    def POP_EXCEPT(self, oparg, next_instr):
        block = self.pop_block()
        assert isinstance(block, SysExcInfoRestorer)
        block.cleanupstack(self)   # restores ec.sys_exc_operror

    def POP_BLOCK(self, oparg, next_instr):
        block = self.pop_block()
        block.pop_block(self)  # the block knows how to clean up the value stack

    def save_and_change_sys_exc_info(self, operationerr):
        ec = self.space.getexecutioncontext()
        last_exception = ec.sys_exc_info()
        block = SysExcInfoRestorer(last_exception, self.lastblock)
        self.lastblock = block
        if operationerr is not None:   # otherwise, don't change sys_exc_info
            if not self.hide():
                ec.set_sys_exc_info(operationerr)
            else:
                # for hidden frames, a more limited solution should be
                # enough: store away the exception on the frame
                self.getorcreatedebug().hidden_operationerr = operationerr

    def end_finally(self):
        # unlike CPython, there are two statically distinct cases: the
        # END_FINALLY might be closing an 'except' block or a 'finally'
        # block.  In the first case, the stack contains three items:
        #   [exception type we are now handling]
        #   [exception value we are now handling]
        #   [wrapped SApplicationException]
        # In the case of a finally: block, the stack contains only one
        # item (unlike CPython which can have 1, 2, 3 or 5 items, and
        # even in one case a non-fixed number of items):
        #   [wrapped subclass of SuspendedUnroller]

        block = self.pop_block()
        assert isinstance(block, SysExcInfoRestorer)
        block.cleanupstack(self)   # restores ec.sys_exc_operror

        w_top = self.popvalue()
        if self.space.is_w(w_top, self.space.w_None):
            # case of a finally: block with no exception
            return None
        if isinstance(w_top, SuspendedUnroller):
            # case of a finally: block with a suspended unroller
            return w_top
        else:
            # case of an except: block.  We popped the exception type
            self.popvalue()        #     Now we pop the exception value
            w_unroller = self.popvalue()
            assert w_unroller is not None
            return w_unroller

    @jit.unroll_safe
    def _any_except_or_finally_handler(self):
        block = self.lastblock
        while block is not None:
            if isinstance(block, SysExcInfoRestorer):
                return True
            block = block.previous
        return False

    def LOAD_BUILD_CLASS(self, oparg, next_instr):
        w_build_class = self.get_builtin().getdictvalue(
            self.space, '__build_class__')
        if w_build_class is None:
            raise oefmt(self.space.w_ImportError, "__build_class__ not found")
        self.pushvalue(w_build_class)

    def STORE_NAME(self, varindex, next_instr):
        varname = self.getname_u(varindex)
        w_newvalue = self.popvalue()
        self.space.setitem_str(self.getorcreatedebug().w_locals, varname,
                               w_newvalue)

    def DELETE_NAME(self, varindex, next_instr):
        w_varname = self.getname_w(varindex)
        try:
            self.space.delitem(self.getorcreatedebug().w_locals, w_varname)
        except OperationError as e:
            # catch KeyErrors and turn them into NameErrors
            if not e.match(self.space, self.space.w_KeyError):
                raise
            raise oefmt(self.space.w_NameError,
                        "__annotations__ not found")

    def UNPACK_SEQUENCE(self, itemcount, next_instr):
        w_iterable = self.popvalue()
        items = self.space.fixedview_unroll(w_iterable, itemcount)
        self.pushrevvalues(itemcount, items)

    @jit.unroll_safe
    def UNPACK_EX(self, oparg, next_instr):
        "a, *b, c = range(10)"
        left = oparg & 0xFF
        right = (oparg & 0xFF00) >> 8
        w_iterable = self.popvalue()
        items = self.space.fixedview(w_iterable)
        itemcount = len(items)
        count = left + right
        if count > itemcount:
            raise oefmt(self.space.w_ValueError,
                        "not enough values to unpack (expected at least %d, got %d)",
                        count, itemcount)
        right = itemcount - right
        assert right >= 0
        # push values in reverse order
        i = itemcount - 1
        while i >= right:
            self.pushvalue(items[i])
            i -= 1
        self.pushvalue(self.space.newlist(items[left:right]))
        i = left - 1
        while i >= 0:
            self.pushvalue(items[i])
            i -= 1

    def STORE_ATTR(self, nameindex, next_instr):
        "obj.attributename = newvalue"
        w_attributename = self.getname_w(nameindex)
        w_obj = self.popvalue()
        w_newvalue = self.popvalue()
        self.space.setattr(w_obj, w_attributename, w_newvalue)

    def DELETE_ATTR(self, nameindex, next_instr):
        "del obj.attributename"
        w_attributename = self.getname_w(nameindex)
        w_obj = self.popvalue()
        self.space.delattr(w_obj, w_attributename)

    def STORE_GLOBAL(self, nameindex, next_instr):
        varname = self.getname_u(nameindex)
        w_newvalue = self.popvalue()
        self.space.setitem_str(self.get_w_globals(), varname, w_newvalue)

    def DELETE_GLOBAL(self, nameindex, next_instr):
        w_varname = self.getname_w(nameindex)
        self.space.delitem(self.get_w_globals(), w_varname)

    def LOAD_NAME(self, nameindex, next_instr):
        w_varname = self.getname_w(nameindex)
        varname = self.space.text_w(w_varname)
        if self.getorcreatedebug().w_locals is not self.get_w_globals():
            w_value = self.space.finditem_str(self.getorcreatedebug().w_locals,
                                              varname)
            if w_value is not None:
                self.pushvalue(w_value)
                return
        # fall-back
        w_value = self._load_global(varname)
        if w_value is None:
            raise oefmt(self.space.w_NameError,
                        "name %R is not defined", w_varname)
        self.pushvalue(w_value)

    @always_inline
    def _load_global(self, varname):
        w_value = self.space.finditem_str(self.get_w_globals(), varname)
        if w_value is None:
            # not in the globals, now look in the built-ins
            w_value = self.get_builtin().getdictvalue(self.space, varname)
        return w_value

    @dont_inline
    def _load_global_failed(self, w_varname):
        # CPython Issue #17032: The "global" in the "NameError: global
        # name 'x' is not defined" error message has been removed.
        raise oefmt(self.space.w_NameError,
                    "name %R is not defined", w_varname)

    @always_inline
    def LOAD_GLOBAL(self, nameindex, next_instr):
        w_varname = self.getname_w(nameindex)
        w_value = self._load_global(self.space.text_w(w_varname))
        if w_value is None:
            self._load_global_failed(w_varname)
        self.pushvalue(w_value)

    def DELETE_FAST(self, varindex, next_instr):
        if self.locals_cells_stack_w[varindex] is None:
            varname = self.getlocalvarname(varindex)
            raise oefmt(self.space.w_UnboundLocalError,
                        "local variable '%s' referenced before assignment",
                        varname)
        self.locals_cells_stack_w[varindex] = None

    def SETUP_ANNOTATIONS(self, oparg, next_instr):
        w_locals = self.getorcreatedebug().w_locals
        if not self.space.finditem_str(w_locals, '__annotations__'):
            w_annotations = self.space.newdict()
            self.space.setitem_str(w_locals, '__annotations__', w_annotations)

    def STORE_ANNOTATION(self, varindex, next_instr):
        space = self.space
        varname = self.getname_u(varindex)
        w_newvalue = self.popvalue()
        w_locals = self.getorcreatedebug().w_locals
        try:
            w_annotations = space.getitem(w_locals, space.newtext('__annotations__'))
        except OperationError as e:
            if e.match(space, space.w_KeyError):
                raise oefmt(space.w_NameError, CANNOT_CATCH_MSG)
            raise
        self.space.setitem_str(w_annotations, varname, w_newvalue)

    def BUILD_TUPLE(self, itemcount, next_instr):
        items = self.popvalues(itemcount)
        w_tuple = self.space.newtuple(items)
        self.pushvalue(w_tuple)

    def BUILD_LIST(self, itemcount, next_instr):
        items = self.popvalues_mutable(itemcount)
        w_list = self.space.newlist(items)
        self.pushvalue(w_list)

    def BUILD_LIST_FROM_ARG(self, _, next_instr):
        space = self.space
        # this is a little dance, because list has to be before the
        # value
        last_val = self.popvalue()
        length_hint = 0
        try:
            length_hint = space.length_hint(last_val, length_hint)
        except OperationError as e:
            if e.async(space):
                raise
        self.pushvalue(space.newlist([], sizehint=length_hint))
        self.pushvalue(last_val)

    @always_inline
    def LOAD_ATTR(self, nameindex, next_instr):
        "obj.attributename"
        w_obj = self.popvalue()
        if not jit.we_are_jitted():
            from pypy.objspace.std.mapdict import LOAD_ATTR_caching
            w_value = LOAD_ATTR_caching(self.getcode(), w_obj, nameindex)
        else:
            w_attributename = self.getname_w(nameindex)
            w_value = self.space.getattr(w_obj, w_attributename)
        self.pushvalue(w_value)

    @jit.unroll_safe
    def cmp_exc_match(self, w_1, w_2):
        space = self.space
        if space.isinstance_w(w_2, space.w_tuple):
            for w_type in space.fixedview(w_2):
                if not space.exception_is_valid_class_w(w_type):
                    raise oefmt(space.w_TypeError, CANNOT_CATCH_MSG)
        elif not space.exception_is_valid_class_w(w_2):
            raise oefmt(space.w_TypeError, CANNOT_CATCH_MSG)
        return space.newbool(space.exception_match(w_1, w_2))

    def COMPARE_OP(self, testnum, next_instr):
        w_2 = self.popvalue()
        w_1 = self.popvalue()
        if testnum == 0:
            w_result = self.space.lt(w_1, w_2)
        elif testnum == 1:
            w_result = self.space.le(w_1, w_2)
        elif testnum == 2:
            w_result = self.space.eq(w_1, w_2)
        elif testnum == 3:
            w_result = self.space.ne(w_1, w_2)
        elif testnum == 4:
            w_result = self.space.gt(w_1, w_2)
        elif testnum == 5:
            w_result = self.space.ge(w_1, w_2)
        elif testnum == 6:
            w_result = self.space.contains(w_2, w_1)
        elif testnum == 7:
            w_result = self.space.not_(self.space.contains(w_2, w_1))
        elif testnum == 8:
            w_result = self.space.is_(w_1, w_2)
        elif testnum == 9:
            w_result = self.space.not_(self.space.is_(w_1, w_2))
        elif testnum == 10:
            w_result = self.cmp_exc_match(w_1, w_2)
        else:
            raise BytecodeCorruption("bad COMPARE_OP oparg")
        self.pushvalue(w_result)

    def IMPORT_NAME(self, nameindex, next_instr):
        space = self.space
        w_modulename = self.getname_w(nameindex)
        modulename = self.space.text_w(w_modulename)
        w_fromlist = self.popvalue()

        w_flag = self.popvalue()
        try:
            if space.int_w(w_flag) == -1:
                w_flag = None
        except OperationError as e:
            if e.async(space):
                raise

        w_import = self.get_builtin().getdictvalue(space, '__import__')
        if w_import is None:
            raise oefmt(space.w_ImportError, "__import__ not found")
        d = self.getdebug()
        if d is None:
            w_locals = None
        else:
            w_locals = d.w_locals
        if w_locals is None:            # CPython does this
            w_locals = space.w_None
        w_modulename = space.newtext(modulename)
        w_globals = self.get_w_globals()
        if w_flag is None:
            w_obj = space.call_function(w_import, w_modulename, w_globals,
                                        w_locals, w_fromlist)
        else:
            w_obj = space.call_function(w_import, w_modulename, w_globals,
                                        w_locals, w_fromlist, w_flag)

        self.pushvalue(w_obj)

    def IMPORT_STAR(self, oparg, next_instr):
        w_module = self.popvalue()
        w_locals = self.getdictscope()
        import_all_from(self.space, w_module, w_locals)
        self.setdictscope(w_locals)

    def IMPORT_FROM(self, nameindex, next_instr):
        w_name = self.getname_w(nameindex)
        w_module = self.peekvalue()
        self.pushvalue(self.import_from(w_module, w_name))

    def import_from(self, w_module, w_name):
        space = self.space
        try:
            return space.getattr(w_module, w_name)
        except OperationError as e:
            if not e.match(space, space.w_AttributeError):
                raise
            try:
                w_pkgname = space.getattr(
                    w_module, space.newtext('__name__'))
                w_fullname = space.newtext(b'%s.%s' %
                    (space.utf8_w(w_pkgname), space.utf8_w(w_name)))
                return space.getitem(space.sys.get('modules'), w_fullname)
            except OperationError:
                raise oefmt(
                    space.w_ImportError, "cannot import name %R", w_name)


    def YIELD_VALUE(self, oparg, next_instr):
        if self.getcode().co_flags & pycode.CO_ASYNC_GENERATOR:
            from pypy.interpreter.generator import AsyncGenValueWrapper
            w_value = self.popvalue()
            w_value = AsyncGenValueWrapper(w_value)
            self.pushvalue(w_value)
        raise Yield

    def next_yield_from(self, w_yf, w_inputvalue_or_err):
        """Fetch the next item of the current 'yield from', push it on
        the frame stack, and raises Yield.  If there isn't one, push
        w_stopiteration_value and returns.  May also just raise.
        """
        from pypy.interpreter.generator import (
            GeneratorOrCoroutine, AsyncGenASend)
        space = self.space
        try:
            if isinstance(w_yf, GeneratorOrCoroutine):
                w_retval = w_yf.send_ex(w_inputvalue_or_err)
            elif isinstance(w_yf, AsyncGenASend):   # performance only
                w_retval = w_yf.do_send(w_inputvalue_or_err)
            elif space.is_w(w_inputvalue_or_err, space.w_None):
                w_retval = space.next(w_yf)
            else:
                w_retval = delegate_to_nongen(space, w_yf, w_inputvalue_or_err)
        except OperationError as e:
            if not e.match(space, space.w_StopIteration):
                raise
            self._report_stopiteration_sometimes(w_yf, e)
            try:
                w_stop_value = space.getattr(e.get_w_value(space),
                                             space.newtext("value"))
            except OperationError as e:
                if not e.match(space, space.w_AttributeError):
                    raise
                w_stop_value = space.w_None
            self.pushvalue(w_stop_value)
            return
        else:
            self.pushvalue(w_retval)
            self.w_yielding_from = w_yf
            raise Yield

    def YIELD_FROM(self, oparg, next_instr):
        # Unlike CPython, we handle this not by repeating the same
        # bytecode over and over until the inner iterator is exhausted.
        # Instead, we set w_yielding_from.
        # This asks resume_execute_frame() to exhaust that
        # sub-iterable first before continuing on the next bytecode.
        w_inputvalue = self.popvalue()    # that's always w_None, actually
        w_gen = self.popvalue()
        #
        self.next_yield_from(w_gen, w_inputvalue)
        # Common case: the call above raises Yield.
        # If instead the iterable is empty, next_yield_from() pushed the
        # final result and returns.  In that case, we can just continue
        # with the next bytecode.

    def _revdb_jump_backward(self, jumpto):
        # moved in its own function for the import statement
        from pypy.interpreter.reverse_debugging import jump_backward
        jump_backward(self, jumpto)

    def jump_absolute(self, jumpto, ec):
        # this function is overridden by pypy.module.pypyjit.interp_jit
        check_nonneg(jumpto)
        if self.space.reverse_debugging:
            self._revdb_jump_backward(jumpto)
        return jumpto

    def JUMP_FORWARD(self, jumpby, next_instr):
        next_instr += jumpby
        return next_instr

    def POP_JUMP_IF_FALSE(self, target, next_instr):
        w_value = self.popvalue()
        if not self.space.is_true(w_value):
            return target
        return next_instr

    def POP_JUMP_IF_TRUE(self, target, next_instr):
        w_value = self.popvalue()
        if self.space.is_true(w_value):
            return target
        return next_instr

    def JUMP_IF_FALSE_OR_POP(self, target, next_instr):
        w_value = self.peekvalue()
        if not self.space.is_true(w_value):
            return target
        self.popvalue()
        return next_instr

    def JUMP_IF_TRUE_OR_POP(self, target, next_instr):
        w_value = self.peekvalue()
        if self.space.is_true(w_value):
            return target
        self.popvalue()
        return next_instr

    def GET_ITER(self, oparg, next_instr):
        w_iterable = self.popvalue()
        w_iterator = self.space.iter(w_iterable)
        self.pushvalue(w_iterator)

    def FOR_ITER(self, jumpby, next_instr):
        w_iterator = self.peekvalue()
        try:
            w_nextitem = self.space.next(w_iterator)
        except OperationError as e:
            if not e.match(self.space, self.space.w_StopIteration):
                raise
            # iterator exhausted
            self._report_stopiteration_sometimes(w_iterator, e)
            self.popvalue()
            next_instr += jumpby
        else:
            self.pushvalue(w_nextitem)
        return next_instr

    def _report_stopiteration_sometimes(self, w_iterator, operr):
        # CPython 3.5 calls the exception trace in an ill-defined subset
        # of cases: only if tp_iternext returned NULL and set a
        # StopIteration exception, but not if tp_iternext returned NULL
        # *without* setting an exception.  We can't easily emulate that
        # behavior at this point.  For example, the generator's
        # tp_iternext uses one or other case depending on whether the
        # generator is already exhausted or just exhausted now.  We'll
        # classify that as a CPython incompatibility and use an
        # approximative rule: if w_iterator is a generator-iterator,
        # we always report it; if operr has already a stack trace
        # attached (likely from a custom __iter__() method), we also
        # report it; in other cases, we don't.
        from pypy.interpreter.generator import GeneratorOrCoroutine
        if (isinstance(w_iterator, GeneratorOrCoroutine) or
                operr.has_any_traceback()):
            self.space.getexecutioncontext().exception_trace(self, operr)

    def FOR_LOOP(self, oparg, next_instr):
        raise BytecodeCorruption("old opcode, no longer in use")

    def SETUP_LOOP(self, offsettoend, next_instr):
        block = LoopBlock(self.valuestackdepth,
                          next_instr + offsettoend, self.lastblock)
        self.lastblock = block

    def SETUP_EXCEPT(self, offsettoend, next_instr):
        block = ExceptBlock(self.valuestackdepth,
                            next_instr + offsettoend, self.lastblock)
        self.lastblock = block

    def SETUP_FINALLY(self, offsettoend, next_instr):
        block = FinallyBlock(self.valuestackdepth,
                             next_instr + offsettoend, self.lastblock)
        self.lastblock = block

    def SETUP_WITH(self, offsettoend, next_instr):
        w_manager = self.peekvalue()
        w_enter = self.space.lookup(w_manager, "__enter__")
        w_descr = self.space.lookup(w_manager, "__exit__")
        if w_enter is None or w_descr is None:
            raise oefmt(self.space.w_AttributeError,
                        "'%T' object is not a context manager (no __enter__/"
                        "__exit__ method)", w_manager)
        w_exit = self.space.get(w_descr, w_manager)
        self.settopvalue(w_exit)
        w_result = self.space.get_and_call_function(w_enter, w_manager)
        block = FinallyBlock(self.valuestackdepth,
                             next_instr + offsettoend, self.lastblock)
        self.lastblock = block
        self.pushvalue(w_result)

    def WITH_CLEANUP_START(self, oparg, next_instr):
        # see comment in END_FINALLY for stack state
        w_unroller = self.popvalue()
        w_exitfunc = self.popvalue()
        self.pushvalue(w_unroller)
        if isinstance(w_unroller, SApplicationException):
            # app-level exception
            operr = w_unroller.operr
            w_traceback = operr.get_w_traceback(self.space)
            w_res = self.call_contextmanager_exit_function(
                w_exitfunc,
                operr.w_type,
                operr.get_w_value(self.space),
                w_traceback)
        else:
            w_res = self.call_contextmanager_exit_function(
                w_exitfunc,
                self.space.w_None,
                self.space.w_None,
                self.space.w_None)
        self.pushvalue(w_res)
        # in the stack now:  [w_res, w_unroller-or-w_None..]

    def WITH_CLEANUP_FINISH(self, oparg, next_instr):
        w_suppress = self.popvalue()
        w_unroller = self.peekvalue()
        if isinstance(w_unroller, SApplicationException):
            if self.space.is_true(w_suppress):
                # __exit__() returned True -> Swallow the exception.
                self.settopvalue(self.space.w_None)
        # this is always followed by END_FINALLY
        # in the stack now: [w_unroller-or-w_None..]

    @jit.unroll_safe
    def call_function(self, oparg, w_starstar=None, has_vararg=False):
        n_arguments = oparg & 0xff
        n_keywords = (oparg>>8) & 0xff
        if n_keywords:
            keywords = [None] * n_keywords
            keywords_w = [None] * n_keywords
            while True:
                n_keywords -= 1
                if n_keywords < 0:
                    break
                w_value = self.popvalue()
                w_key = self.popvalue()
                key = self.space.text_w(w_key)
                keywords[n_keywords] = key
                keywords_w[n_keywords] = w_value
        else:
            keywords = None
            keywords_w = None
        if has_vararg:
            w_star = self.popvalue()
        else:
            w_star = None
        arguments = self.popvalues(n_arguments)
        w_function  = self.popvalue()
        args = self.argument_factory(arguments, keywords, keywords_w, w_star,
                                     w_starstar, w_function=w_function)
        if self.get_is_being_profiled() and function.is_builtin_code(w_function):
            w_result = self.space.call_args_and_c_profile(self, w_function,
                                                          args)
        else:
            w_result = self.space.call_args(w_function, args)
        self.pushvalue(w_result)

    def CALL_FUNCTION(self, oparg, next_instr):
        # Only positional arguments
        nargs = oparg & 0xff
        w_function = self.peekvalue(nargs)
        try:
            w_result = self.space.call_valuestack(w_function, nargs, self)
        finally:
            self.dropvalues(nargs + 1)
        self.pushvalue(w_result)

    @jit.unroll_safe
    def CALL_FUNCTION_KW(self, n_arguments, next_instr):
        w_tup_varnames = self.popvalue()
        keywords_w = self.space.fixedview(w_tup_varnames)
        n_keywords = len(keywords_w)
        n_arguments -= n_keywords
        keywords = [self.space.text_w(w_keyword) for w_keyword in keywords_w]
        keywords_w = [None] * n_keywords
        while True:
            n_keywords -= 1
            if n_keywords < 0:
                break
            w_value = self.popvalue()
            keywords_w[n_keywords] = w_value
        arguments = self.popvalues(n_arguments)
        w_function  = self.popvalue()
        args = self.argument_factory(arguments, keywords, keywords_w, None, None,
                                     w_function=w_function)
        if self.get_is_being_profiled() and function.is_builtin_code(w_function):
            w_result = self.space.call_args_and_c_profile(self, w_function,
                                                          args)
        else:
            w_result = self.space.call_args(w_function, args)
        self.pushvalue(w_result)

    def CALL_FUNCTION_EX(self, has_kwarg, next_instr):
        w_kwargs = None
        if has_kwarg:
            w_kwargs = self.popvalue()
        w_args = self.popvalue()
        w_function = self.popvalue()
        args = self.argument_factory(
            [], None, None, w_star=w_args, w_starstar=w_kwargs, w_function=w_function)
        if self.get_is_being_profiled() and function.is_builtin_code(w_function):
            w_result = self.space.call_args_and_c_profile(self, w_function,
                                                          args)
        else:
            w_result = self.space.call_args(w_function, args)
        self.pushvalue(w_result)

    @jit.unroll_safe
    def MAKE_FUNCTION(self, oparg, next_instr):
        space = self.space
        w_qualname = self.popvalue()
        qualname = self.space.utf8_w(w_qualname)
        w_codeobj = self.popvalue()
        codeobj = self.space.interp_w(PyCode, w_codeobj)
        assert 0 <= oparg <= 0x0F
        if oparg & 0x08:
            w_freevarstuple = self.popvalue()
            # XXX this list copy is expensive, it's purely for the annotator
            freevars = [self.space.interp_w(Cell, cell)
                        for cell in self.space.fixedview(w_freevarstuple)]
        else:
            freevars = None
        if oparg & 0x04:
            w_ann = self.popvalue()
        else:
            w_ann = None
        if oparg & 0x02:
            w_kw_defs = self.popvalue()
            # XXX
            kw_defs_w = [space.unpackiterable(w_tup)
                            for w_tup in space.fixedview(
                                space.call_method(w_kw_defs, 'items'))]
        else:
            kw_defs_w = None
        if oparg & 0x01:
            defaultarguments = space.fixedview(self.popvalue())
        else:
            defaultarguments = []

        fn = function.Function(space, codeobj, self.get_w_globals(),
                               defaultarguments,
                               kw_defs_w, freevars, w_ann, qualname=qualname)
        self.pushvalue(fn)

    def BUILD_SLICE(self, numargs, next_instr):
        if numargs == 3:
            w_step = self.popvalue()
        elif numargs == 2:
            w_step = self.space.w_None
        else:
            raise BytecodeCorruption
        w_end = self.popvalue()
        w_start = self.popvalue()
        w_slice = self.space.newslice(w_start, w_end, w_step)
        self.pushvalue(w_slice)

    def LIST_APPEND(self, oparg, next_instr):
        w = self.popvalue()
        v = self.peekvalue(oparg - 1)
        self.space.call_method(v, 'append', w)

    def SET_ADD(self, oparg, next_instr):
        w_value = self.popvalue()
        w_set = self.peekvalue(oparg - 1)
        self.space.call_method(w_set, 'add', w_value)

    def MAP_ADD(self, oparg, next_instr):
        w_key = self.popvalue()
        w_value = self.popvalue()
        w_dict = self.peekvalue(oparg - 1)
        self.space.setitem(w_dict, w_key, w_value)

    def SET_LINENO(self, lineno, next_instr):
        pass

    # overridden by faster version in the standard object space.
    LOOKUP_METHOD = LOAD_ATTR
    CALL_METHOD = CALL_FUNCTION
    CALL_METHOD_KW = CALL_FUNCTION_KW

    def MISSING_OPCODE(self, oparg, next_instr):
        ofs = self.last_instr
        c = self.pycode.co_code[ofs]
        name = self.pycode.co_name
        raise BytecodeCorruption("unknown opcode, ofs=%d, code=%d, name=%s" %
                                 (ofs, ord(c), name) )

    @jit.unroll_safe
    def BUILD_MAP(self, itemcount, next_instr):
        w_dict = self.space.newdict()
        for i in range(itemcount-1, -1, -1):
            w_value = self.peekvalue(2 * i)
            w_key = self.peekvalue(2 * i + 1)
            self.space.setitem(w_dict, w_key, w_value)
        self.dropvalues(2 * itemcount)
        self.pushvalue(w_dict)

    @jit.unroll_safe
    def BUILD_CONST_KEY_MAP(self, itemcount, next_instr):
        from pypy.objspace.std.tupleobject import W_AbstractTupleObject
        # the reason why we don't use space.fixedview here is that then the
        # immutability of the tuple would not propagate into the loop below in
        # the JIT
        w_keys = self.space.interp_w(W_AbstractTupleObject, self.popvalue())
        w_dict = self.space.newdict()
        for i in range(itemcount):
            w_value = self.peekvalue(itemcount - 1 - i)
            w_key = w_keys.getitem(self.space, i)
            self.space.setitem(w_dict, w_key, w_value)
        self.dropvalues(itemcount)
        self.pushvalue(w_dict)

    @jit.unroll_safe
    def BUILD_SET(self, itemcount, next_instr):
        w_set = self.space.newset()
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            self.space.call_method(w_set, 'add', w_item)
        self.dropvalues(itemcount)
        self.pushvalue(w_set)

    @jit.unroll_safe
    def BUILD_SET_UNPACK(self, itemcount, next_instr):
        space = self.space
        w_set = space.newset()
        for i in range(itemcount, 0, -1):
            w_item = self.peekvalue(i-1)
            space.call_method(w_set, "update", w_item)
        self.popvalues(itemcount)
        self.pushvalue(w_set)

    @jit.unroll_safe
    def BUILD_TUPLE_UNPACK(self, itemcount, next_instr):
        l = []
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            l.extend(self.space.fixedview(w_item))
        self.popvalues(itemcount)
        self.pushvalue(self.space.newtuple(l[:]))

    @jit.unroll_safe
    def BUILD_LIST_UNPACK(self, itemcount, next_instr):
        space = self.space
        w_sum = space.newlist([], sizehint=itemcount)
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            w_sum.extend(w_item)
        self.popvalues(itemcount)
        self.pushvalue(w_sum)

    def BUILD_MAP_UNPACK(self, itemcount, next_instr):
        self._build_map_unpack(itemcount, with_call=False)

    def BUILD_MAP_UNPACK_WITH_CALL(self, oparg, next_instr):
        num_maps = oparg # XXX CPython generates better error messages
        self._build_map_unpack(num_maps, with_call=True)

    @jit.unroll_safe
    def _build_map_unpack(self, itemcount, with_call):
        space = self.space
        w_dict = space.newdict()
        expected_length = 0
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            if not space.ismapping_w(w_item):
                if not with_call:
                    raise oefmt(space.w_TypeError,
                                "'%T' object is not a mapping", w_item)
                else:
                    raise oefmt(space.w_TypeError,
                                "argument after ** must be a mapping, not %T",
                                w_item)
            if with_call:
                expected_length += space.len_w(w_item)
            space.call_method(w_dict, 'update', w_item)
        if with_call and space.len_w(w_dict) < expected_length:
            self._build_map_unpack_error(itemcount)
        self.popvalues(itemcount)
        self.pushvalue(w_dict)

    @jit.dont_look_inside
    def _build_map_unpack_error(self, itemcount):
        space = self.space
        w_set = space.newset()
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            w_inter = space.call_method(w_set, 'intersection', w_item)
            if space.is_true(w_inter):
                w_key = space.next(space.iter(w_inter))
                if not space.isinstance_w(w_key, space.w_unicode):
                    raise oefmt(space.w_TypeError,
                            "keywords must be strings, not '%T'", w_key)
                raise oefmt(space.w_TypeError,
                    "got multiple values for keyword argument %R",
                    w_key)
            space.call_method(w_set, 'update', w_item)

    def GET_YIELD_FROM_ITER(self, oparg, next_instr):
        from pypy.interpreter.astcompiler import consts
        from pypy.interpreter.generator import GeneratorIterator, Coroutine
        w_iterable = self.peekvalue()
        if isinstance(w_iterable, Coroutine):
            if not self.pycode.co_flags & (consts.CO_COROUTINE |
                                       consts.CO_ITERABLE_COROUTINE):
                #'iterable' coroutine is used in a 'yield from' expression
                #of a regular generator
                raise oefmt(self.space.w_TypeError,
                            "cannot 'yield from' a coroutine object "
                            "in a non-coroutine generator")
        elif not isinstance(w_iterable, GeneratorIterator):
            w_iterator = self.space.iter(w_iterable)
            self.settopvalue(w_iterator)

    def GET_AWAITABLE(self, oparg, next_instr):
        from pypy.interpreter.generator import get_awaitable_iter
        from pypy.interpreter.generator import Coroutine
        w_iterable = self.popvalue()
        w_iter = get_awaitable_iter(self.space, w_iterable)
        if isinstance(w_iter, Coroutine):
            if w_iter.get_delegate() is not None:
                # 'w_iter' is a coroutine object that is being awaited,
                # '.w_yielded_from' is the current awaitable being awaited on.
                raise oefmt(self.space.w_RuntimeError,
                            "coroutine is being awaited already")
        self.pushvalue(w_iter)

    def SETUP_ASYNC_WITH(self, offsettoend, next_instr):
        res = self.popvalue()
        block = FinallyBlock(self.valuestackdepth,
                             next_instr + offsettoend, self.lastblock)
        self.lastblock = block
        self.pushvalue(res)

    def BEFORE_ASYNC_WITH(self, oparg, next_instr):
        space = self.space
        w_manager = self.peekvalue()
        w_enter = space.lookup(w_manager, "__aenter__")
        w_descr = space.lookup(w_manager, "__aexit__")
        if w_enter is None or w_descr is None:
            raise oefmt(space.w_AttributeError,
                        "'%T' object is not a context manager (no __aenter__/"
                        "__aexit__ method)", w_manager)
        w_exit = space.get(w_descr, w_manager)
        self.settopvalue(w_exit)
        w_result = space.get_and_call_function(w_enter, w_manager)
        self.pushvalue(w_result)

    def GET_AITER(self, oparg, next_instr):
        from pypy.interpreter.generator import AIterWrapper, get_awaitable_iter

        space = self.space
        w_obj = self.popvalue()
        w_func = space.lookup(w_obj, "__aiter__")
        if w_func is None:
            raise oefmt(space.w_TypeError,
                        "'async for' requires an object with "
                        "__aiter__ method, got %T",
                        w_obj)
        w_iter = space.get_and_call_function(w_func, w_obj)

        # If __aiter__() returns an object with a __anext__() method,
        # wrap it in a awaitable that resolves to 'w_iter'.
        if space.lookup(w_iter, "__anext__") is not None:
            w_awaitable = AIterWrapper(w_iter)
        else:
            try:
                w_awaitable = get_awaitable_iter(space, w_iter)
            except OperationError as e:
                if e.async(space):
                    raise
                new_error = oefmt(space.w_TypeError,
                            "'async for' received an invalid object "
                            "from __aiter__: %T", w_iter)
                e.normalize_exception(space)
                new_error.normalize_exception(space)
                new_error.set_cause(space, e.get_w_value(space))
                raise new_error
            space.warn(space.newtext(
                "'%s' implements legacy __aiter__ protocol; "
                "__aiter__ should return an asynchronous "
                "iterator, not awaitable" %
                    space.type(w_obj).name),
                space.w_DeprecationWarning)
        self.pushvalue(w_awaitable)

    def GET_ANEXT(self, oparg, next_instr):
        from pypy.interpreter.generator import get_awaitable_iter

        # XXX add performance shortcut if w_aiter is an AsyncGenerator
        space = self.space
        w_aiter = self.peekvalue()
        w_func = space.lookup(w_aiter, "__anext__")
        if w_func is None:
            raise oefmt(space.w_TypeError,
                        "'async for' requires an iterator with "
                        "__anext__ method, got %T",
                        w_aiter)
        w_next_iter = space.get_and_call_function(w_func, w_aiter)
        try:
            w_awaitable = get_awaitable_iter(space, w_next_iter)
        except OperationError as e:
            if e.async(space):
                raise
            new_error = oefmt(space.w_TypeError,
                        "'async for' received an invalid object "
                        "from __anext__: %T", w_next_iter)
            e.normalize_exception(space)
            new_error.normalize_exception(space)
            new_error.set_cause(space, e.get_w_value(space))
            raise new_error
        self.pushvalue(w_awaitable)

    def FORMAT_VALUE(self, oparg, next_instr):
        from pypy.interpreter.astcompiler import consts
        space = self.space
        #
        if (oparg & consts.FVS_MASK) == consts.FVS_HAVE_SPEC:
            w_spec = self.popvalue()
        else:
            w_spec = space.newtext('')
        w_value = self.popvalue()
        #
        conversion = oparg & consts.FVC_MASK
        if conversion == consts.FVC_STR:
            w_value = space.str(w_value)
        elif conversion == consts.FVC_REPR:
            w_value = space.repr(w_value)
        elif conversion == consts.FVC_ASCII:
            from pypy.objspace.std.unicodeobject import ascii_from_object
            w_value = ascii_from_object(space, w_value)
        #
        w_res = space.format(w_value, w_spec)
        self.pushvalue(w_res)

    @jit.unroll_safe
    def BUILD_STRING(self, itemcount, next_instr):
        space = self.space
        lst = []
        for i in range(itemcount-1, -1, -1):
            w_item = self.peekvalue(i)
            lst.append(space.utf8_w(w_item))
        self.dropvalues(itemcount)
        w_res = space.newtext(''.join(lst))
        self.pushvalue(w_res)

    def _revdb_load_var(self, oparg):
        # moved in its own function for the import statement
        from pypy.interpreter.reverse_debugging import load_metavar
        w_var = load_metavar(oparg)
        self.pushvalue(w_var)

    def LOAD_REVDB_VAR(self, oparg, next_instr):
        if self.space.reverse_debugging:
            self._revdb_load_var(oparg)
        else:
            self.MISSING_OPCODE(oparg, next_instr)

def delegate_to_nongen(space, w_yf, w_inputvalue_or_err):
    # invoke a "send" or "throw" by method name to a non-generator w_yf
    if isinstance(w_inputvalue_or_err, SApplicationException):
        operr = w_inputvalue_or_err.operr
        try:
            w_meth = space.getattr(w_yf, space.newtext("throw"))
        except OperationError as e:
            if not e.match(space, space.w_AttributeError):
                raise
            raise operr
        # bah, CPython calls here with the exact same arguments as
        # originally passed to throw().  In our case it is far removed.
        # Let's hope nobody will complain...
        operr.normalize_exception(space)
        w_exc = operr.w_type
        w_val = operr.get_w_value(space)
        w_tb = operr.get_w_traceback(space)
        return space.call_function(w_meth, w_exc, w_val, w_tb)
    else:
        return space.call_method(w_yf, "send", w_inputvalue_or_err)


### ____________________________________________________________ ###

class ExitFrame(Exception):
    pass


class Return(ExitFrame):
    """Raised when exiting a frame via a 'return' statement."""


class Yield(ExitFrame):
    """Raised when exiting a frame via a 'yield' statement."""


class RaiseWithExplicitTraceback(Exception):
    """Raised at interp-level by a 0-argument 'raise' statement."""
    def __init__(self, operr):
        self.operr = operr


### Frame Blocks ###

class SuspendedUnroller(W_Root):
    """Abstract base class for interpreter-level objects that
    instruct the interpreter to change the control flow and the
    block stack.

    The concrete subclasses correspond to the various values WHY_XXX
    values of the why_code enumeration in ceval.c:

                WHY_NOT,        OK, not this one :-)
                WHY_EXCEPTION,  SApplicationException
                WHY_RERAISE,    implemented differently, see Reraise
                WHY_RETURN,     SReturnValue
                WHY_BREAK,      SBreakLoop
                WHY_CONTINUE,   SContinueLoop
                WHY_YIELD       not needed
    """
    _immutable_ = True
    def nomoreblocks(self):
        raise BytecodeCorruption("misplaced bytecode - should not return")

class SReturnValue(SuspendedUnroller):
    """Signals a 'return' statement.
    Argument is the wrapped object to return."""
    _immutable_ = True
    kind = 0x01
    def __init__(self, w_returnvalue):
        self.w_returnvalue = w_returnvalue
    def nomoreblocks(self):
        return self.w_returnvalue

class SApplicationException(SuspendedUnroller):
    """Signals an application-level exception
    (i.e. an OperationException)."""
    _immutable_ = True
    kind = 0x02
    def __init__(self, operr):
        self.operr = operr
    def nomoreblocks(self):
        raise RaiseWithExplicitTraceback(self.operr)

class SBreakLoop(SuspendedUnroller):
    """Signals a 'break' statement."""
    _immutable_ = True
    kind = 0x04
SBreakLoop.singleton = SBreakLoop()

class SContinueLoop(SuspendedUnroller):
    """Signals a 'continue' statement.
    Argument is the bytecode position of the beginning of the loop."""
    _immutable_ = True
    kind = 0x08
    def __init__(self, jump_to):
        self.jump_to = jump_to


class FrameBlock(object):
    """Abstract base class for frame blocks from the blockstack,
    used by the SETUP_XXX and POP_BLOCK opcodes."""

    _immutable_ = True

    def __init__(self, valuestackdepth, handlerposition, previous):
        self.handlerposition = handlerposition
        self.valuestackdepth = valuestackdepth
        self.previous = previous   # this makes a linked list of blocks

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
                self.handlerposition == other.handlerposition and
                self.valuestackdepth == other.valuestackdepth)

    def __ne__(self, other):
        return not (self == other)

    def __hash__(self):
        return hash((self.handlerposition, self.valuestackdepth))

    def cleanupstack(self, frame):
        frame.dropvaluesuntil(self.valuestackdepth)

    def pop_block(self, frame):
        "Clean up a frame when we normally exit the block."
        self.cleanupstack(frame)

    # internal pickling interface, not using the standard protocol
    def _get_state_(self, space):
        return space.newtuple([space.newtext(self._opname), space.newint(self.handlerposition),
                               space.newint(self.valuestackdepth)])

    def handle(self, frame, unroller):
        """ Purely abstract method
        """
        raise NotImplementedError

class LoopBlock(FrameBlock):
    """A loop block.  Stores the end-of-loop pointer in case of 'break'."""

    _immutable_ = True
    _opname = 'SETUP_LOOP'
    handling_mask = SBreakLoop.kind | SContinueLoop.kind

    def handle(self, frame, unroller):
        if isinstance(unroller, SContinueLoop):
            # re-push the loop block without cleaning up the value stack,
            # and jump to the beginning of the loop, stored in the
            # exception's argument
            frame.append_block(self)
            jumpto = unroller.jump_to
            ec = frame.space.getexecutioncontext()
            return r_uint(frame.jump_absolute(jumpto, ec))
        else:
            # jump to the end of the loop
            self.cleanupstack(frame)
            return r_uint(self.handlerposition)


class SysExcInfoRestorer(FrameBlock):
    """
    This is a special, implicit block type which is created when entering a
    finally or except handler. It does not belong to any opcode
    """

    _immutable_ = True
    _opname = 'SYS_EXC_INFO_RESTORER' # it's not associated to any opcode
    handling_mask = 0 # this block is never handled, only popped by POP_EXCEPT

    def __init__(self, operr, previous):
        self.operr = operr
        self.previous = previous

    def pop_block(self, frame):
        assert False # never called

    def handle(self, frame, unroller):
        assert False # never called

    def cleanupstack(self, frame):
        ec = frame.space.getexecutioncontext()
        ec.set_sys_exc_info(self.operr)


class ExceptBlock(FrameBlock):
    """An try:except: block.  Stores the position of the exception handler."""

    _immutable_ = True
    _opname = 'SETUP_EXCEPT'
    handling_mask = SApplicationException.kind

    def handle(self, frame, unroller):
        # push the exception to the value stack for inspection by the
        # exception handler (the code after the except:)
        self.cleanupstack(frame)
        # the stack setup is slightly different than in CPython:
        # instead of the traceback, we store the unroller object,
        # wrapped.
        assert isinstance(unroller, SApplicationException)
        operationerr = unroller.operr
        operationerr.normalize_exception(frame.space)
        frame.pushvalue(unroller)
        frame.pushvalue(operationerr.get_w_value(frame.space))
        frame.pushvalue(operationerr.w_type)
        # set the current value of sys_exc_info to operationerr,
        # saving the old value in a custom type of FrameBlock
        frame.save_and_change_sys_exc_info(operationerr)
        return r_uint(self.handlerposition)   # jump to the handler


class FinallyBlock(FrameBlock):
    """A try:finally: block.  Stores the position of the exception handler."""

    _immutable_ = True
    _opname = 'SETUP_FINALLY'
    handling_mask = -1     # handles every kind of SuspendedUnroller

    def handle(self, frame, unroller):
        # any abnormal reason for unrolling a finally: triggers the end of
        # the block unrolling and the entering the finally: handler.
        # see comments in cleanup().
        self.cleanupstack(frame)
        operationerr = None
        if isinstance(unroller, SApplicationException):
            operationerr = unroller.operr
            operationerr.normalize_exception(frame.space)
        frame.pushvalue(unroller)
        # set the current value of sys_exc_info to operationerr,
        # saving the old value in a custom type of FrameBlock
        frame.save_and_change_sys_exc_info(operationerr)
        return r_uint(self.handlerposition)   # jump to the handler

    def pop_block(self, frame):
        self.cleanupstack(frame)
        frame.save_and_change_sys_exc_info(None)


block_classes = {'SYS_EXC_INFO_RESTORER': SysExcInfoRestorer,
                 'SETUP_LOOP': LoopBlock,
                 'SETUP_EXCEPT': ExceptBlock,
                 'SETUP_FINALLY': FinallyBlock,
                 'SETUP_WITH': FinallyBlock,
                 }


##class W_OperationError(W_Root):
##    """
##    Tiny applevel wrapper around an OperationError.
##    """
##
##    def __init__(self, operr):
##        self.operr = operr
##
##    def descr_reduce(self, space):
##        from pypy.interpreter.mixedmodule import MixedModule
##        w_mod = space.getbuiltinmodule('_pickle_support')
##        mod = space.interp_w(MixedModule, w_mod)
##        w_new_inst = mod.get('operationerror_new')
##        w_args = space.newtuple([])
##        operr = self.operr
##        if operr is None:
##            return space.newtuple([w_new_inst, w_args])
##        w_state = space.newtuple([operr.w_type, operr.get_w_value(space),
##                                  operr.get_traceback()])
##        return space.newtuple([w_new_inst, w_args, w_state])
##
##    def descr_setstate(self, space, w_state):
##        w_type, w_value, w_tb = space.fixedview(w_state, 3)
##        self.operr = OperationError(w_type, w_value, w_tb)

def source_as_str(space, w_source, funcname, what, flags):
    """Return source code as str0 with adjusted compiler flags

    w_source must be a str or support the buffer interface
    """
    from pypy.interpreter.astcompiler import consts

    if space.isinstance_w(w_source, space.w_unicode):
        from pypy.interpreter.unicodehelper import encode
        w_source = encode(space, w_source)
        source = space.bytes_w(w_source)
        flags |= consts.PyCF_IGNORE_COOKIE
    elif space.isinstance_w(w_source, space.w_bytes):
        source = space.bytes_w(w_source)
    else:
        try:
            buf = space.buffer_w(w_source, space.BUF_SIMPLE)
        except OperationError as e:
            if not e.match(space, space.w_TypeError):
                raise
            raise oefmt(space.w_TypeError,
                        "%s() arg 1 must be a %s object", funcname, what)
        source = buf.as_str()

    if not (flags & consts.PyCF_ACCEPT_NULL_BYTES):
        if '\x00' in source:
            raise oefmt(space.w_ValueError,
                        "source code string cannot contain null bytes")
        source = rstring.assert_str0(source)
    return source, flags


def ensure_ns(space, w_globals, w_locals, funcname, caller=None):
    """Ensure globals/locals exist and are of the correct type"""
    if (not space.is_none(w_globals) and
        not space.isinstance_w(w_globals, space.w_dict)):
        raise oefmt(space.w_TypeError,
                    '%s() arg 2 must be a dict, not %T', funcname, w_globals)
    if (not space.is_none(w_locals) and
        space.lookup(w_locals, '__getitem__') is None):
        raise oefmt(space.w_TypeError,
                    '%s() arg 3 must be a mapping or None, not %T',
                    funcname, w_locals)

    if space.is_none(w_globals):
        if caller is None:
            caller = space.getexecutioncontext().gettopframe_nohidden()
        if caller is None:
            w_globals = space.newdict(module=True)
            if space.is_none(w_locals):
                w_locals = w_globals
        else:
            w_globals = caller.get_w_globals()
            if space.is_none(w_locals):
                w_locals = caller.getdictscope()
    elif space.is_none(w_locals):
        w_locals = w_globals

    return w_globals, w_locals


### helpers written at the application-level ###
# Some of these functions are expected to be generally useful if other
# parts of the code need to do the same thing as a non-trivial opcode,
# like finding out which metaclass a new class should have.
# This is why they are not methods of PyFrame.
# There are also a couple of helpers that are methods, defined in the
# class above.

app = gateway.applevel(r'''
    """ applevel implementation of certain system properties, imports
    and other helpers"""
    import sys

    def sys_stdout():
        try:
            return sys.stdout
        except AttributeError:
            raise RuntimeError("lost sys.stdout")

    def print_expr(obj):
        try:
            displayhook = sys.displayhook
        except AttributeError:
            raise RuntimeError("lost sys.displayhook")
        displayhook(obj)

    def print_item_to(x, stream):
        # give to write() an argument which is either a string or a unicode
        # (and let it deals itself with unicode handling).  The check "is
        # unicode" should not use isinstance() at app-level, because that
        # could be fooled by strange objects, so it is done at interp-level.
        try:
            stream.write(x)
        except UnicodeEncodeError:
            print_unencodable_to(x, stream)

    def print_unencodable_to(x, stream):
        encoding = stream.encoding
        encoded = x.encode(encoding, 'backslashreplace')
        buffer = getattr(stream, 'buffer', None)
        if buffer is not None:
             buffer.write(encoded)
        else:
            escaped = encoded.decode(encoding, 'strict')
            stream.write(escaped)

    def print_item(x):
        print_item_to(x, sys_stdout())

    def print_newline_to(stream):
        stream.write("\n")

    def print_newline():
        print_newline_to(sys_stdout())
''', filename=__file__)

sys_stdout      = app.interphook('sys_stdout')
print_expr      = app.interphook('print_expr')
print_item      = app.interphook('print_item')
print_item_to   = app.interphook('print_item_to')
print_newline   = app.interphook('print_newline')
print_newline_to= app.interphook('print_newline_to')

app = gateway.applevel(r'''
    def find_metaclass(bases, namespace, globals, builtin):
        if '__metaclass__' in namespace:
            return namespace['__metaclass__']
        elif len(bases) > 0:
            base = bases[0]
            if hasattr(base, '__class__'):
                return base.__class__
            else:
                return type(base)
        elif '__metaclass__' in globals:
            return globals['__metaclass__']
        else:
            try:
                return builtin.__metaclass__
            except AttributeError:
                return type
''', filename=__file__)

find_metaclass  = app.interphook('find_metaclass')

app = gateway.applevel(r'''
    def import_all_from(module, into_locals):
        try:
            all = module.__all__
        except AttributeError:
            try:
                dict = module.__dict__
            except AttributeError:
                raise ImportError("from-import-* object has no __dict__ "
                                  "and no __all__")
            all = dict.keys()
            skip_leading_underscores = True
        else:
            skip_leading_underscores = False
        for name in all:
            if skip_leading_underscores and name and name[0] == '_':
                continue
            into_locals[name] = getattr(module, name)
''', filename=__file__)

import_all_from = app.interphook('import_all_from')
