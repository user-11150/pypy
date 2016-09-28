from rpython.jit.metainterp.walkvirtual import VirtualVisitor
from rpython.jit.metainterp.history import ConstInt, ConstPtr, ConstFloat
from rpython.jit.metainterp.optimizeopt.info import ArrayPtrInfo,\
     ArrayStructInfo, AbstractStructPtrInfo
from rpython.jit.metainterp.optimizeopt.intutils import \
     MININT, MAXINT, IntBound, IntLowerBound, IntUnbounded
from rpython.jit.metainterp.resoperation import rop, ResOperation, \
     InputArgInt, InputArgRef, InputArgFloat
from rpython.rlib.debug import debug_print
from rpython.rlib.objectmodel import specialize

LEVEL_UNKNOWN = '\x00'
LEVEL_NONNULL = '\x01'
LEVEL_KNOWNCLASS = '\x02'
LEVEL_CONSTANT = '\x03'

class VirtualStatesCantMatch(Exception):
    def __init__(self, msg='?', state=None):
        self.msg = msg
        self.state = state


class GenerateGuardState(object):
    _attrs_ = ('optimizer', 'cpu', 'extra_guards', 'renum', 'bad', 'force_boxes')

    def __init__(self, optimizer=None, guards=None, renum=None, bad=None, force_boxes=False):
        self.optimizer = optimizer
        self.cpu = optimizer.cpu
        if guards is None:
            guards = []
        self.extra_guards = guards
        if renum is None:
            renum = {}
        self.renum = renum
        if bad is None:
            bad = {}
        self.bad = bad
        self.force_boxes = force_boxes

    def get_runtime_item(self, box, descr, i):
        array = box.getref_base()
        if descr.is_array_of_pointers():
            return InputArgRef(self.cpu.bh_getarrayitem_gc_r(array, i, descr))
        elif descr.is_array_of_floats():
            return InputArgFloat(self.cpu.bh_getarrayitem_gc_f(array, i, descr))
        else:
            return InputArgInt(self.cpu.bh_getarrayitem_gc_i(array, i, descr))

    def get_runtime_field(self, box, descr):
        struct = box.getref_base()
        if descr.is_pointer_field():
            return InputArgRef(self.cpu.bh_getfield_gc_r(struct, descr))
        elif descr.is_float_field():
            return InputArgFloat(self.cpu.bh_getfield_gc_f(struct, descr))
        else:
            return InputArgInt(self.cpu.bh_getfield_gc_i(struct, descr))

    def get_runtime_interiorfield(self, box, descr, i):
        struct = box.getref_base()
        if descr.is_pointer_field():
            return InputArgRef(self.cpu.bh_getinteriorfield_gc_r(struct, i,
                                                                 descr))
        elif descr.is_float_field():
            return InputArgFloat(self.cpu.bh_getinteriorfield_gc_f(struct, i,
                                                                   descr))
        else:
            return InputArgInt(self.cpu.bh_getinteriorfield_gc_i(struct, i,
                                                                 descr))

class AbstractVirtualStateInfo(object):
    _attrs_ = ('position', 'fieldstate')
    position = -1

    def generate_guards(self, other, op, runtime_op, state):
        """ generate guards (output in the list extra_guards) that make runtime
        values of the shape other match the shape of self. if that's not
        possible, VirtualStatesCantMatch is thrown and bad gets keys set which
        parts of the state are the problem.

        the function can peek into the information about the op, as well
        as runtime value (passed in runtime_op)
        as a guiding heuristic whether making such guards makes
        sense. if None is passed in for op, no guard is ever generated, and
        this function degenerates to a generalization check."""
        assert self.position != -1
        if self.position in state.renum:
            if state.renum[self.position] != other.position:
                state.bad[self] = state.bad[other] = None
                raise VirtualStatesCantMatch(
                        'The numbering of the virtual states does not ' +
                        'match. This means that two virtual fields ' +
                        'have been set to the same Box in one of the ' +
                        'virtual states but not in the other.',
                        state)
        else:
            state.renum[self.position] = other.position
            try:
                self._generate_guards(other, op, runtime_op, state)
            except VirtualStatesCantMatch as e:
                state.bad[self] = state.bad[other] = None
                if e.state is None:
                    e.state = state
                raise e

    def _generate_guards(self, other, box, runtime_box, state):
        raise VirtualStatesCantMatch(
                'Generating guards for making the VirtualStates ' +
                'at hand match have not been implemented')

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        raise NotImplementedError

    def enum(self, virtual_state):
        if self.position != -1:
            return
        virtual_state.info_counter += 1
        self.position = virtual_state.info_counter
        self._enum(virtual_state)

    def _enum(self, virtual_state):
        raise NotImplementedError

    def debug_print(self, indent, seen, bad, metainterp_sd):
        mark = ''
        if self in bad:
            mark = '*'
        self.debug_header(indent + mark)
        if self not in seen:
            seen[self] = True
            for s in self.fieldstate:
                s.debug_print(indent + "    ", seen, bad, metainterp_sd)
        else:
            debug_print(indent + "    ...")

    def debug_header(self, indent):
        raise NotImplementedError

class AbstractVirtualStructStateInfo(AbstractVirtualStateInfo):
    _attrs_ = ('typedescr', 'fielddescrs')

    def __init__(self, typedescr, fielddescrs):
        self.typedescr = typedescr
        self.fielddescrs = fielddescrs

    def _generate_guards(self, other, box, runtime_box, state):
        if isinstance(other, NotVirtualStateInfo):
            return self._generate_guards_non_virtual(other, box, runtime_box, state)

        if not self._generalization_of_structpart(other):
            raise VirtualStatesCantMatch("different kinds of structs")

        assert isinstance(other, AbstractVirtualStructStateInfo)
        assert len(self.fielddescrs) == len(self.fieldstate)
        assert len(other.fielddescrs) == len(other.fieldstate)
        if runtime_box is not None:
            opinfo = state.optimizer.getptrinfo(box)
            assert opinfo.is_virtual()
            assert isinstance(opinfo, AbstractStructPtrInfo)
        else:
            opinfo = None

        if len(self.fielddescrs) != len(other.fielddescrs):
            raise VirtualStatesCantMatch("field descrs don't match")

        for i in range(len(self.fielddescrs)):
            if other.fielddescrs[i] is not self.fielddescrs[i]:
                raise VirtualStatesCantMatch("field descrs don't match")
            if runtime_box is not None and opinfo is not None:
                fieldbox = opinfo._fields[self.fielddescrs[i].get_index()]
                if fieldbox is not None:
                    fieldbox_runtime = state.get_runtime_field(runtime_box,
                                                           self.fielddescrs[i])
                else:
                    fieldbox_runtime = None
            else:
                fieldbox = None
                fieldbox_runtime = None
            if self.fieldstate[i] is not None:
                if other.fieldstate[i] is None:
                    raise VirtualStatesCantMatch
                self.fieldstate[i].generate_guards(other.fieldstate[i],
                                                   fieldbox,
                                                   fieldbox_runtime, state)

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        box = optimizer.get_box_replacement(box)
        info = optimizer.getptrinfo(box)
        if info is None or not info.is_virtual():
            raise VirtualStatesCantMatch()
        else:
            assert isinstance(info, AbstractStructPtrInfo)

        # The min operation ensures we don't wander off either array, as not all
        # to make_inputargs have validated their inputs with generate_guards.
        for i in range(min(len(self.fielddescrs), len(info._fields))):
            state = self.fieldstate[i]
            if not state:
                continue
            if state.position > self.position:
                fieldbox = info._fields[i]
                state.enum_forced_boxes(boxes, fieldbox, optimizer, force_boxes)

    def _enum(self, virtual_state):
        for s in self.fieldstate:
            if s:
                s.enum(virtual_state)

class VirtualStateInfo(AbstractVirtualStructStateInfo):
    _attrs_ = ('known_class',)

    def __init__(self, typedescr, fielddescrs):
        AbstractVirtualStructStateInfo.__init__(self, typedescr, fielddescrs)
        self.known_class = ConstInt(typedescr.get_vtable())

    def _generalization_of_structpart(self, other):
        return (isinstance(other, VirtualStateInfo) and
                self.typedescr is other.typedescr)

    @specialize.argtype(4)
    def getfield(self, box, info, descr, optimizer):
        assert isinstance(info, AbstractStructPtrInfo)
        field = info._fields[descr.get_index()]
        if field is not None:
            return field
        opnum = rop.getfield_for_descr(descr)
        getfield = ResOperation(opnum, [box], descr=descr)
        if isinstance(optimizer, list):
            optimizer.append(getfield)
        else:
            from rpython.jit.metainterp.optimizeopt import Optimizer
            assert isinstance(optimizer, Optimizer)
            optimizer.emit_operation(getfield)
        info._fields[descr.get_index()] = getfield
        return getfield

    def make_virtual_copy(self, box, info, optimizer):
        optvirtualize = optimizer.optvirtualize
        opinfo = optvirtualize.make_virtual(self.known_class, box, self.typedescr)
        for i in range(len(info._fields)):
            descr = self.fielddescrs[i]
            opinfo._fields[i] = self.getfield(box, info, descr, optimizer)
        return opinfo

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        box = optimizer.get_box_replacement(box)
        info = optimizer.getptrinfo(box)

        if (not self.typedescr.is_value_class() or
            info is None or info.is_virtual()):
            return AbstractVirtualStructStateInfo.enum_forced_boxes(
                    self, boxes, box, optimizer, force_boxes)

        assert isinstance(info, AbstractStructPtrInfo)

        # TODO: Do we need to create a new object via NEW_WITH_VTABLE, or will the
        # allocation be handled properly?
        opinfo = self.make_virtual_copy(box, info, optimizer.optimizer)
        for i in range(min(len(self.fielddescrs), len(opinfo._fields))):
            state = self.fieldstate[i]
            if state is None:
                continue
            if state.position > self.position:
                fieldbox = opinfo._fields[i]
                state.enum_forced_boxes(boxes, fieldbox, optimizer, force_boxes)

    def _generate_guards_non_virtual(self, other, box, runtime_box, state):
        """
        Generate guards for the case where a virtual object is expected, but
        a non-virtual is given. When the underlying type is a value class,
        the non-virtual may be virtualized by unpacking it and forwarding the
        components elementwise.
        """
        assert isinstance(other, NotVirtualStateInfoPtr)

        if not self.typedescr.is_value_class():
            raise VirtualStatesCantMatch("different kinds of structs")

        # raise VirtualStatesCantMatch("different kinds of structs")
        # TODO: Probably should rename state.extra_guards to extra_ops
        extra_guards = state.extra_guards
        cpu = state.cpu

        # Emit any guards that are needed to validate the class of the supplied
        # object, so that we know it is safe to unpack.
        if other.level == LEVEL_UNKNOWN:
            op = ResOperation(rop.GUARD_NONNULL_CLASS, [box, self.known_class])
            extra_guards.append(op)
        elif other.level == LEVEL_NONNULL:
            op = ResOperation(rop.GUARD_CLASS, [box, self.known_class])
            extra_guards.append(op)
        elif other.level == LEVEL_KNOWNCLASS:
            if not self.known_class.same_constant(other.known_class):
                raise VirtualStatesCantMatch("classes don't match")
        else:
            assert other.level == LEVEL_CONSTANT
            known = self.known_class
            const = other.constbox
            if const.nonnull() and known.same_constant(cpu.ts.cls_of_box(const)):
                pass
            else:
                raise VirtualStatesCantMatch("classes don't match")

        # Things to do...
        # 1. Generate new_with_vtable operation to allocate the new virtual object
        # 2. Generate getfield operations which populate the fields of the new virtual
        # 3. Recursively generate guards for each portion of the virtual state
        #    (we don't have a VirtualStateInfo objects for the subfields of the
        #     non-virtual object which we are promoting to a virtual. How do we
        #     generate this new virtual state so we can operate recursively)

        if runtime_box is not None:
            opinfo = state.optimizer.getptrinfo(box)
            assert opinfo is None or isinstance(opinfo, AbstractStructPtrInfo)
        else:
            opinfo = None

        # We need to build a virtual version which conforms with the expected
        # virtual object.
        # This will probably look a lot like
        # AbstractVirtualStateInfo._generate_guards
        for i, descr in enumerate(self.fielddescrs):
            if runtime_box is not None and opinfo is not None:
                fieldbox = self.getfield(box, opinfo, descr, extra_guards)
                fieldbox_runtime = state.get_runtime_field(runtime_box, descr)
            else:
                opnum = rop.getfield_for_descr(descr)
                fieldbox = ResOperation(opnum, [box], descr=descr)
                extra_guards.append(fieldbox)
                fieldbox_runtime = None
            fieldstate = self.fieldstate[i]
            if fieldstate is not None:
                other_field_state = not_virtual(cpu, fieldbox.type, opinfo)
                fieldstate.generate_guards(other_field_state, fieldbox,
                                           fieldbox_runtime, state)

    def debug_header(self, indent):
        debug_print(indent + 'VirtualStateInfo(%d):' % self.position)

class VStructStateInfo(AbstractVirtualStructStateInfo):

    def _generalization_of_structpart(self, other):
        return (isinstance(other, VStructStateInfo) and
                self.typedescr is other.typedescr)

    def _generate_guards_non_virtual(self, other, box, runtime_box, state):
        raise VirtualStatesCantMatch("can't unify virtual struct with non-virtual")

    def debug_header(self, indent):
        debug_print(indent + 'VStructStateInfo(%d):' % self.position)

class VArrayStateInfo(AbstractVirtualStateInfo):
    _attrs_ = ('arraydescr',)

    def __init__(self, arraydescr):
        self.arraydescr = arraydescr

    def _generate_guards(self, other, box, runtime_box, state):
        if not isinstance(other, VArrayStateInfo):
            raise VirtualStatesCantMatch("other is not an array")
        if self.arraydescr is not other.arraydescr:
            raise VirtualStatesCantMatch("other is a different kind of array")
        if len(self.fieldstate) != len(other.fieldstate):
            raise VirtualStatesCantMatch("other has a different length")
        fieldbox = None
        fieldbox_runtime = None
        for i in range(len(self.fieldstate)):
            if runtime_box is not None:
                opinfo = state.optimizer.getptrinfo(box)
                assert isinstance(opinfo, ArrayPtrInfo)
                fieldbox = opinfo._items[i]
                fieldbox_runtime = state.get_runtime_item(runtime_box,
                                            self.arraydescr, i)
            if self.fieldstate[i] is not None:
                if other.fieldstate[i] is None:
                    raise VirtualStatesCantMatch
                self.fieldstate[i].generate_guards(other.fieldstate[i],
                                            fieldbox, fieldbox_runtime, state)

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        box = optimizer.get_box_replacement(box)
        info = optimizer.getptrinfo(box)
        if info is None or not info.is_virtual():
            raise VirtualStatesCantMatch()
        if len(self.fieldstate) > info.getlength():
            raise VirtualStatesCantMatch
        for i in range(len(self.fieldstate)):
            fieldbox = info.getitem(self.arraydescr, i)
            s = self.fieldstate[i]
            if s is not None:
                if s.position > self.position:
                    s.enum_forced_boxes(boxes, fieldbox, optimizer, force_boxes)

    def _enum(self, virtual_state):
        for s in self.fieldstate:
            if s:
                s.enum(virtual_state)

    def debug_header(self, indent):
        debug_print(indent + 'VArrayStateInfo(%d):' % self.position)


class VArrayStructStateInfo(AbstractVirtualStateInfo):
    _attrs_ = ('arraydescr', 'fielddescrs', 'length')

    def __init__(self, arraydescr, fielddescrs, length):
        self.arraydescr = arraydescr
        self.fielddescrs = fielddescrs
        self.length = length

    def _generate_guards(self, other, box, runtime_box, state):
        if not isinstance(other, VArrayStructStateInfo):
            raise VirtualStatesCantMatch("other is not an VArrayStructStateInfo")
        if self.arraydescr is not other.arraydescr:
            raise VirtualStatesCantMatch("other is a different kind of array")

        if len(self.fielddescrs) != len(other.fielddescrs):
            raise VirtualStatesCantMatch("other has a different length")

        if len(self.fielddescrs) != len(other.fielddescrs):
            raise VirtualStatesCantMatch("other has a different length")
        for j, descr in enumerate(self.fielddescrs):
            if descr is not other.fielddescrs[j]:
                raise VirtualStatesCantMatch("other is a different kind of array")
        fieldbox = None
        fieldbox_runtime = None
        if box is not None:
            opinfo = state.optimizer.getptrinfo(box)
            assert isinstance(opinfo, ArrayPtrInfo)
        else:
            opinfo = None
        for i in range(self.length):
            for descr in self.fielddescrs:
                index = i * len(self.fielddescrs) + descr.get_index()
                fieldstate = self.fieldstate[index]
                if fieldstate is None:
                    continue
                if other.fieldstate[index] is None:
                    raise VirtualStatesCantMatch
                if box is not None and opinfo is not None:
                    fieldbox = opinfo._items[index]
                    fieldbox_runtime = state.get_runtime_interiorfield(
                        runtime_box, descr, i)
                self.fieldstate[index].generate_guards(other.fieldstate[index],
                                       fieldbox, fieldbox_runtime, state)

    def _enum(self, virtual_state):
        for s in self.fieldstate:
            if s is not None:
                s.enum(virtual_state)

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        opinfo = optimizer.getptrinfo(box)
        if not isinstance(opinfo, ArrayStructInfo):
            raise VirtualStatesCantMatch
        if not opinfo.is_virtual():
            raise VirtualStatesCantMatch
        #if len(self.fielddescrs) > len(value._items):
        #    raise VirtualStatesCantMatch
        for i in range(self.length):
            for descr in self.fielddescrs:
                index = i * len(self.fielddescrs) + descr.get_index()
                fieldstate = self.fieldstate[index]
                itembox = opinfo._items[i * len(self.fielddescrs) +
                                        descr.get_index()]
                if fieldstate is None:
                    if itembox is not None:
                        raise VirtualStatesCantMatch
                    continue
                # I think itembox must be present here
                if fieldstate.position > self.position:
                    fieldstate.enum_forced_boxes(boxes, itembox, optimizer,
                                                 force_boxes)

    def debug_header(self, indent):
        debug_print(indent + 'VArrayStructStateInfo(%d):' % self.position)


def not_virtual(cpu, type, info):
    if type == 'i':
        return NotVirtualStateInfoInt(cpu, type, info)
    if type == 'r':
        return NotVirtualStateInfoPtr(cpu, type, info)
    assert type == 'f'
    return NotVirtualStateInfo(cpu, type, info)


class NotVirtualStateInfo(AbstractVirtualStateInfo):
    _attrs_ = ('level', 'constbox', 'position_in_notvirtuals')
    level = LEVEL_UNKNOWN
    constbox = None

    def __init__(self, cpu, type, info):
        if info and info.is_constant():
            self.level = LEVEL_CONSTANT
            self.constbox = info.getconst()

    def _generate_guards(self, other, box, runtime_box, state):
        # XXX This will always retrace instead of forcing anything which
        # might be what we want sometimes?
        extra_guards = state.extra_guards
        if self.level == LEVEL_UNKNOWN:
            return self._generate_guards_unkown(other, box, runtime_box,
                                                extra_guards,
                                                state)
        else:
            if not isinstance(other, NotVirtualStateInfo):
                raise VirtualStatesCantMatch(
                        'comparing a constant against something that is a virtual')
            assert self.level == LEVEL_CONSTANT
            if other.level == LEVEL_CONSTANT:
                if self.constbox.same_constant(other.constbox):
                    return
                raise VirtualStatesCantMatch("different constants")
            if runtime_box is not None and self.constbox.same_constant(runtime_box.constbox()):
                op = ResOperation(rop.GUARD_VALUE, [box, self.constbox])
                extra_guards.append(op)
                return
            else:
                raise VirtualStatesCantMatch("other not constant")
        assert 0, "unreachable"

    def _generate_guards_unkown(self, other, box, runtime_box, extra_guards,
                                state):
        return

    def enum_forced_boxes(self, boxes, box, optimizer, force_boxes=False):
        if self.level == LEVEL_CONSTANT:
            return
        assert 0 <= self.position_in_notvirtuals
        if optimizer is not None:
            box = optimizer.get_box_replacement(box)
            if box.type == 'r':
                info = optimizer.getptrinfo(box)
                if info and info.is_virtual():
                    if force_boxes:
                        info.force_box(box, optimizer)
                    else:
                        raise VirtualStatesCantMatch
        boxes[self.position_in_notvirtuals] = box

    def _enum(self, virtual_state):
        if self.level == LEVEL_CONSTANT:
            return
        self.position_in_notvirtuals = virtual_state.numnotvirtuals
        virtual_state.numnotvirtuals += 1

    def debug_print(self, indent, seen, bad, metainterp_sd=None):
        mark = ''
        if self in bad:
            mark = '*'
        if self.level == LEVEL_UNKNOWN:
            l = "Unknown"
        elif self.level == LEVEL_NONNULL:
            l = "NonNull"
        elif self.level == LEVEL_KNOWNCLASS:
            addr = self.known_class.getaddr()
            if metainterp_sd:
                name = metainterp_sd.get_name_from_address(addr)
            else:
                name = "?"
            l = "KnownClass(%s)" % name
        else:
            assert self.level == LEVEL_CONSTANT
            const = self.constbox
            if isinstance(const, ConstInt):
                l = "ConstInt(%s)" % (const.value, )
            elif isinstance(const, ConstPtr):
                if const.value:
                    l = "ConstPtr"
                else:
                    l = "ConstPtr(null)"
            else:
                assert isinstance(const, ConstFloat)
                l = "ConstFloat(%s)" % const.getfloat()

        lb = ''
        if self.lenbound:
            lb = ', ' + self.lenbound.bound.__repr__()

        result = indent + mark + 'NotVirtualStateInfo(%d' % self.position + ', ' + l
        extra = self._extra_repr()
        if extra:
            result += ', ' + extra
        result += lb + ')'
        debug_print(result)

class NotVirtualStateInfoInt(NotVirtualStateInfo):
    _attrs_ = ('intbound')
    intbound = None

    def __init__(self, cpu, type, info):
        NotVirtualStateInfo.__init__(self, cpu, type, info)
        assert type == 'i'
        if isinstance(info, IntBound):
            if info.lower < MININT / 2:
                info.lower = MININT
            if info.upper > MAXINT / 2:
                info.upper = MAXINT
            self.intbound = info

    def _generate_guards_unkown(self, other, box, runtime_box, extra_guards,
                                state):
        other_intbound = None
        if isinstance(other, NotVirtualStateInfoInt):
            other_intbound = other.intbound
        if self.intbound is None:
            return
        if other_intbound is None:
            self.intbound.make_guards(box, extra_guards, state.optimizer)
            return
        if self.intbound.contains_bound(other_intbound):
            return
        if (runtime_box is not None and
            self.intbound.contains(runtime_box.getint())):
            # this may generate a few more guards than needed, but they are
            # optimized away when emitting them
            self.intbound.make_guards(box, extra_guards, state.optimizer)
            return
        raise VirtualStatesCantMatch("intbounds don't match")

    def _extra_repr(self):
        return self.intbound.__repr__()


class NotVirtualStateInfoPtr(NotVirtualStateInfo):
    _attrs_ = ('lenbound', 'known_class')
    lenbound = None
    known_class = None

    def __init__(self, cpu, type, info):
        if info:
            self.known_class = info.get_known_class(cpu)
            if self.known_class:
                self.level = LEVEL_KNOWNCLASS
            elif info.is_nonnull():
                self.level = LEVEL_NONNULL
            self.lenbound = info.getlenbound(None)
        # might set it to LEVEL_CONSTANT
        NotVirtualStateInfo.__init__(self, cpu, type, info)

    def _generate_guards(self, other, box, runtime_box, state):
        if state.force_boxes and isinstance(other, VirtualStateInfo):
            return self._generate_virtual_guards(other, box, runtime_box, state)
        if not isinstance(other, NotVirtualStateInfoPtr):
            raise VirtualStatesCantMatch(
                    'The VirtualStates does not match as a ' +
                    'virtual appears where a pointer is needed ' +
                    'and it is too late to force it.')
        extra_guards = state.extra_guards
        if self.lenbound:
            if other.lenbound is None:
                other_bound = IntLowerBound(0)
            else:
                other_bound = other.lenbound
            if not self.lenbound.contains_bound(other_bound):
                raise VirtualStatesCantMatch("length bound does not match")
        if self.level == LEVEL_NONNULL:
            return self._generate_guards_nonnull(other, box, runtime_box,
                                                 extra_guards,
                                                 state)
        elif self.level == LEVEL_KNOWNCLASS:
            return self._generate_guards_knownclass(other, box, runtime_box,
                                                    extra_guards,
                                                    state)
        return NotVirtualStateInfo._generate_guards(self, other, box,
                                                    runtime_box, state)


    # the following methods often peek into the runtime value that the
    # box had when tracing. This value is only used as an educated guess.
    # It is used here to choose between either emitting a guard and jumping
    # to an existing compiled loop or retracing the loop. Both alternatives
    # will always generate correct behaviour, but performance will differ.

    def _generate_virtual_guards(self, other, box, runtime_box, state):
        """
        Generate the guards and add state information for unifying a virtual
        object with a non-virtual. This involves forcing the object in the
        event that unification can succeed. Since virtual objects cannot be null,
        this method need only check that the virtual object has the expected type.
        """
        assert state.force_boxes and isinstance(other, VirtualStateInfo)

        if self.level == LEVEL_CONSTANT:
            raise VirtualStatesCantMatch(
                    "cannot unify a constant value with a virtual object")

        if self.level == LEVEL_KNOWNCLASS:
            if not self.known_class.same_constant(other.known_class):
                raise VirtualStatesCantMatch("classes don't match")

    def _generate_guards_nonnull(self, other, box, runtime_box, extra_guards,
                                 state):
        if not isinstance(other, NotVirtualStateInfoPtr):
            raise VirtualStatesCantMatch('trying to match ptr with non-ptr??!')
        if other.level == LEVEL_UNKNOWN:
            if runtime_box is not None and runtime_box.nonnull():
                op = ResOperation(rop.GUARD_NONNULL, [box])
                extra_guards.append(op)
                return
            else:
                raise VirtualStatesCantMatch("other not known to be nonnull")
        elif other.level == LEVEL_NONNULL:
            pass
        elif other.level == LEVEL_KNOWNCLASS:
            pass # implies nonnull
        else:
            assert other.level == LEVEL_CONSTANT
            assert other.constbox
            if not other.constbox.nonnull():
                raise VirtualStatesCantMatch("constant is null")

    def _generate_guards_knownclass(self, other, box, runtime_box, extra_guards,
                                    state):
        cpu = state.cpu
        if not isinstance(other, NotVirtualStateInfoPtr):
            raise VirtualStatesCantMatch('trying to match ptr with non-ptr??!')
        if other.level == LEVEL_UNKNOWN:
            if (runtime_box and runtime_box.nonnull() and
                  self.known_class.same_constant(cpu.ts.cls_of_box(runtime_box))):
                op = ResOperation(rop.GUARD_NONNULL_CLASS, [box, self.known_class])
                extra_guards.append(op)
            else:
                raise VirtualStatesCantMatch("other's class is unknown")
        elif other.level == LEVEL_NONNULL:
            if (runtime_box and self.known_class.same_constant(
                    cpu.ts.cls_of_box(runtime_box))):
                op = ResOperation(rop.GUARD_CLASS, [box, self.known_class])
                extra_guards.append(op)
            else:
                raise VirtualStatesCantMatch("other's class is unknown")
        elif other.level == LEVEL_KNOWNCLASS:
            if self.known_class.same_constant(other.known_class):
                return
            raise VirtualStatesCantMatch("classes don't match")
        else:
            assert other.level == LEVEL_CONSTANT
            if (other.constbox.nonnull() and
                    self.known_class.same_constant(cpu.ts.cls_of_box(other.constbox))):
                pass
            else:
                raise VirtualStatesCantMatch("classes don't match")


class VirtualState(object):
    def __init__(self, state):
        self.state = state
        self.info_counter = -1
        self.numnotvirtuals = 0
        for s in state:
            if s:
                s.enum(self)

    def generalization_of(self, other, optimizer):
        state = GenerateGuardState(optimizer)
        assert len(self.state) == len(other.state)
        try:
            for i in range(len(self.state)):
                self.state[i].generate_guards(other.state[i], None, None, state)
        except VirtualStatesCantMatch:
            return False
        return True

    def generate_guards(self, other, boxes, runtime_boxes, optimizer, force_boxes=False):
        assert (len(self.state) == len(other.state) == len(boxes) ==
                len(runtime_boxes))
        state = GenerateGuardState(optimizer, force_boxes=force_boxes)
        for i in range(len(self.state)):
            self.state[i].generate_guards(other.state[i], boxes[i],
                                          runtime_boxes[i], state)
        return state

    def make_inputargs(self, inputargs, optimizer, force_boxes=False):
        if optimizer.optearlyforce:
            optimizer = optimizer.optearlyforce
        assert len(inputargs) == len(self.state)
        boxes = [None] * self.numnotvirtuals

        # We try twice. The first time around we allow boxes to be forced
        # which might change the virtual state if the box appear in more
        # than one place among the inputargs.
        if force_boxes:
            for i in range(len(inputargs)):
                self.state[i].enum_forced_boxes(boxes, inputargs[i], optimizer,
                                                True)
        for i in range(len(inputargs)):
            self.state[i].enum_forced_boxes(boxes, inputargs[i], optimizer)

        return boxes

    def make_inputargs_and_virtuals(self, inputargs, optimizer, force_boxes=False):
        inpargs = self.make_inputargs(inputargs, optimizer, force_boxes)
        # we append the virtuals here in case some stuff is proven
        # to be not a virtual and there are getfields in the short preamble
        # that will read items out of there
        virtuals = []
        for i in range(len(inputargs)):
            if not isinstance(self.state[i], NotVirtualStateInfo):
                virtuals.append(inputargs[i])

        return inpargs, virtuals

    def debug_print(self, hdr='', bad=None, metainterp_sd=None):
        if bad is None:
            bad = {}
        debug_print(hdr + "VirtualState():")
        seen = {}
        for s in self.state:
            s.debug_print("    ", seen, bad, metainterp_sd)


class VirtualStateConstructor(VirtualVisitor):

    def __init__(self, optimizer):
        self.fieldboxes = {}
        self.optimizer = optimizer
        self.info = {}

    def register_virtual_fields(self, keybox, fieldboxes):
        self.fieldboxes[keybox] = fieldboxes

    def already_seen_virtual(self, keybox):
        return keybox in self.fieldboxes

    def create_state_or_none(self, box, opt):
        if box is None:
            return None
        return self.create_state(box, opt)

    def create_state(self, box, opt):
        box = opt.get_box_replacement(box)
        try:
            return self.info[box]
        except KeyError:
            pass
        if box.type == 'r':
            info = opt.getptrinfo(box)
            if info is not None and info.is_virtual():
                result = info.visitor_dispatch_virtual_type(self)
                self.info[box] = result
                info.visitor_walk_recursive(box, self, opt)
                result.fieldstate = [self.create_state_or_none(b, opt)
                                     for b in self.fieldboxes[box]]
            else:
                result = self.visit_not_virtual(box)
                self.info[box] = result
        elif box.type == 'i' or box.type == 'f':
            result = self.visit_not_virtual(box)
            self.info[box] = result
        else:
            assert False
        return result

    def get_virtual_state(self, jump_args):
        if self.optimizer.optearlyforce:
            opt = self.optimizer.optearlyforce
        else:
            opt = self.optimizer
        state = []
        self.info = {}
        for box in jump_args:
            state.append(self.create_state(box, opt))
        return VirtualState(state)

    def visit_not_virtual(self, box):
        return not_virtual(self.optimizer.cpu, box.type,
                           self.optimizer.getinfo(box))

    def visit_virtual(self, typedescr, fielddescrs):
        assert typedescr.is_object()
        return VirtualStateInfo(typedescr, fielddescrs)

    def visit_vstruct(self, typedescr, fielddescrs):
        assert not typedescr.is_object()
        return VStructStateInfo(typedescr, fielddescrs)

    def visit_varray(self, arraydescr, clear):
        # 'clear' is ignored here.  I *think* it is correct, because so
        # far in force_at_end_of_preamble() we force all array values
        # to be non-None, so clearing is not important any more
        return VArrayStateInfo(arraydescr)

    def visit_varraystruct(self, arraydescr, length, fielddescrs):
        return VArrayStructStateInfo(arraydescr, fielddescrs, length)
