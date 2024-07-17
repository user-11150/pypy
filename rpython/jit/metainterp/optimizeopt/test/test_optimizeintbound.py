from __future__ import print_function

import pytest

import operator

from rpython.jit.metainterp.optimizeopt.test.test_optimizebasic import BaseTestBasic
from rpython.jit.metainterp.optimizeopt.intutils import MININT, MAXINT
from rpython.jit.metainterp.optimizeopt.intdiv import magic_numbers
from rpython.jit.metainterp.optimize import InvalidLoop
from rpython.rlib.rarithmetic import intmask, r_uint, LONG_BIT


class TestOptimizeIntBounds(BaseTestBasic):
    def test_very_simple(self):
        ops = """
        [i]
        i0 = int_sub(i, 1)
        guard_value(i0, 0) [i0]
        jump(i0)
        """
        expected = """
        [i]
        i0 = int_sub(i, 1)
        guard_value(i0, 0) [i0]
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_simple(self):
        ops = """
        [i]
        i0 = int_sub(i, 1)
        guard_value(i0, 0) [i0]
        jump(i)
        """
        expected = """
        [i]
        i0 = int_sub(i, 1)
        guard_value(i0, 0) [i0]
        jump(1)
        """
        self.optimize_loop(ops, expected)

    def test_constant_propagate(self):
        ops = """
        []
        i0 = int_add(2, 3)
        i1 = int_is_true(i0)
        guard_true(i1) []
        i2 = int_is_zero(i1)
        guard_false(i2) []
        guard_value(i0, 5) []
        jump()
        """
        expected = """
        []
        jump()
        """
        self.optimize_loop(ops, expected)

    def test_constant_propagate_ovf(self):
        ops = """
        []
        i0 = int_add_ovf(2, 3)
        guard_no_overflow() []
        i1 = int_is_true(i0)
        guard_true(i1) []
        i2 = int_is_zero(i1)
        guard_false(i2) []
        guard_value(i0, 5) []
        jump()
        """
        expected = """
        []
        jump()
        """
        self.optimize_loop(ops, expected)

    def test_const_guard_value(self):
        ops = """
        []
        i = int_add(5, 3)
        guard_value(i, 8) []
        jump()
        """
        expected = """
        []
        jump()
        """
        self.optimize_loop(ops, expected)

    def test_int_is_true_1(self):
        ops = """
        [i0]
        i1 = int_is_true(i0)
        guard_true(i1) []
        i2 = int_is_true(i0)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_is_true(i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_true_is_zero(self):
        ops = """
        [i0]
        i1 = int_is_true(i0)
        guard_true(i1) []
        i2 = int_is_zero(i0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_is_true(i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i2 = int_is_zero(i0)
        guard_false(i2) []
        i1 = int_is_true(i0)
        guard_true(i1) []
        jump(i0)
        """
        expected = """
        [i0]
        i2 = int_is_zero(i0)
        guard_false(i2) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_zero_int_is_true(self):
        ops = """
        [i0]
        i1 = int_is_zero(i0)
        guard_true(i1) []
        i2 = int_is_true(i0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_is_zero(i0)
        guard_true(i1) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_remove_duplicate_pure_op_ovf(self):
        ops = """
        [i1]
        i3 = int_add_ovf(i1, 1)
        guard_no_overflow() []
        i3b = int_is_true(i3)
        guard_true(i3b) []
        i4 = int_add_ovf(i1, 1)
        guard_no_overflow() []
        i4b = int_is_true(i4)
        guard_true(i4b) []
        jump(i3, i4)
        """
        expected = """
        [i1]
        i3 = int_add_ovf(i1, 1)
        guard_no_overflow() []
        i3b = int_is_true(i3)
        guard_true(i3b) []
        jump(i3, i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_and_or_with_zero(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 0)
        i3 = int_and(0, i2)
        i4 = int_or(i2, i1)
        i5 = int_or(i0, i3)
        jump(i4, i5)
        """
        expected = """
        [i0, i1]
        jump(i1, i0)
        """
        self.optimize_loop(ops, expected)

    def test_fold_partially_constant_ops(self):
        ops = """
        [i0]
        i1 = int_sub(i0, 0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_add(i0, 0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_add(0, i0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul(0, i0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul(1, i0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_fold_partially_constant_ops_ovf(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(i0, 0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_add_ovf(i0, 0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_add_ovf(0, i0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul_ovf(0, i0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul_ovf(i0, 0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul_ovf(1, i0)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i1 = int_mul_ovf(i0, 1)
        guard_no_overflow() []
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)


    def test_guard_value_to_guard_true(self):
        ops = """
        [i]
        i1 = int_lt(i, 3)
        guard_value(i1, 1) [i]
        jump(i)
        """
        expected = """
        [i]
        i1 = int_lt(i, 3)
        guard_true(i1) [i]
        jump(i)
        """
        self.optimize_loop(ops, expected)

    def test_guard_value_to_guard_false(self):
        ops = """
        [i]
        i1 = int_is_true(i)
        guard_value(i1, 0) [i]
        jump(i)
        """
        expected = """
        [i]
        i1 = int_is_true(i)
        guard_false(i1) [i]
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_guard_value_on_nonbool(self):
        ops = """
        [i]
        i1 = int_add(i, 3)
        guard_value(i1, 0) [i]
        jump(i)
        """
        expected = """
        [i]
        i1 = int_add(i, 3)
        guard_value(i1, 0) [i]
        jump(-3)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_true_of_bool(self):
        ops = """
        [i0, i1]
        i2 = int_gt(i0, i1)
        i3 = int_is_true(i2)
        i4 = int_is_true(i3)
        guard_value(i4, 0) [i0, i1]
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_lt(i1, i0)
        guard_false(i2) [i0, i1]
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_constant_boolrewrite_lt(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        i2 = int_ge(i0, 0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_constant_boolrewrite_gt(self):
        ops = """
        [i0]
        i1 = int_gt(i0, 0)
        guard_true(i1) []
        i2 = int_le(i0, 0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(0, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_constant_boolrewrite_reflex(self):
        ops = """
        [i0]
        i1 = int_gt(i0, 0)
        guard_true(i1) []
        i2 = int_lt(0, i0)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(0, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_constant_boolrewrite_reflex_invers(self):
        ops = """
        [i0]
        i1 = int_gt(i0, 0)
        guard_true(i1) []
        i2 = int_ge(0, i0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(0, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_remove_consecutive_guard_value_constfold(self):
        ops = """
        [i0]
        guard_value(i0, 0) []
        i1 = int_add(i0, 1)
        guard_value(i1, 1) []
        i2 = int_add(i1, 2)
        jump(i2)
        """
        expected = """
        [i0]
        guard_value(i0, 0) []
        jump(3)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_lt(i0, 5)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_noguard(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        i2 = int_lt(i0, 5)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        i2 = int_lt(i0, 5)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_noopt(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_false(i1) []
        i2 = int_lt(i0, 5)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_false(i1) []
        i2 = int_lt(i0, 5)
        guard_true(i2) []
        jump(4)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_rev(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_false(i1) []
        i2 = int_gt(i0, 3)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_false(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_tripple(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        i2 = int_lt(i0, 7)
        guard_true(i2) []
        i3 = int_lt(i0, 5)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_add(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_add(i0, 10)
        i3 = int_lt(i2, 15)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_add(i0, 10)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_add_ovf_before(self):
        ops = """
        [i0]
        i2 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i3 = int_lt(i2, 15)
        guard_true(i3) []
        i1 = int_lt(i0, 6)
        guard_true(i1) []
        jump(i0)
        """
        expected = """
        [i0]
        i2 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i3 = int_lt(i2, 15)
        guard_true(i3) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_neg_sequence(self):
        # check the trace that we get in practice for int_neg, via
        # ll_int_neg_ovf in rint.py
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        i2 = int_eq(i0, %s)
        guard_false(i2) []
        i3 = int_neg(i0)
        i4 = int_ge(i3, 0)
        guard_true(i4) []
        jump()
        """ % (MININT, )
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_true(i1) []
        i2 = int_eq(i0, %s)
        guard_false(i2) []
        i3 = int_neg(i0)
        jump()
        """ % (MININT, )
        self.optimize_loop(ops, expected)

    def test_bound_lt_add_ovf(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i3 = int_lt(i2, 15)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_add(i0, 10)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_sub(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i1p = int_gt(i0, -4)
        guard_true(i1p) []
        i2 = int_sub(i0, 10)
        i3 = int_lt(i2, -5)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i1p = int_lt(-4, i0)
        guard_true(i1p) []
        i2 = int_sub(i0, 10)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lt_sub_before(self):
        ops = """
        [i0]
        i2 = int_sub(i0, 10)
        i3 = int_lt(i2, -5)
        guard_true(i3) []
        i1 = int_lt(i0, 5)
        guard_true(i1) []
        jump(i0)
        """
        expected = """
        [i0]
        i2 = int_sub(i0, 10)
        i3 = int_lt(i2, -5)
        guard_true(i3) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_ltle(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        i2 = int_le(i0, 3)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lelt(self):
        ops = """
        [i0]
        i1 = int_le(i0, 4)
        guard_true(i1) []
        i2 = int_lt(i0, 5)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_le(i0, 4)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_gt(self):
        ops = """
        [i0]
        i1 = int_gt(i0, 5)
        guard_true(i1) []
        i2 = int_gt(i0, 4)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(5, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_gtge(self):
        ops = """
        [i0]
        i1 = int_gt(i0, 5)
        guard_true(i1) []
        i2 = int_ge(i0, 6)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(5, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_gegt(self):
        ops = """
        [i0]
        i1 = int_ge(i0, 5)
        guard_true(i1) []
        i2 = int_gt(i0, 4)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_le(5, i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_ovf(self):
        ops = """
        [i0]
        i1 = int_ge(i0, 0)
        guard_true(i1) []
        i2 = int_lt(i0, 10)
        guard_true(i2) []
        i3 = int_add_ovf(i0, 1)
        guard_no_overflow() []
        jump(i3)
        """
        expected = """
        [i0]
        i1 = int_le(0, i0)
        guard_true(i1) []
        i2 = int_lt(i0, 10)
        guard_true(i2) []
        i3 = int_add(i0, 1)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_addsub_int(self):
        ops = """
        [i0, i10]
        i1 = int_add(i0, i10)
        i2 = int_sub(i1, i10)
        i3 = int_add(i2, i10)
        i4 = int_add(i2, i3)
        jump(i4, i10)
        """
        expected = """
        [i0, i10]
        i1 = int_add(i0, i10)
        i4 = int_add(i0, i1)
        jump(i4, i10)
        """
        self.optimize_loop(ops, expected)

    def test_addsub_int2(self):
        ops = """
        [i0, i10]
        i1 = int_add(i10, i0)
        i2 = int_sub(i1, i10)
        i3 = int_add(i10, i2)
        i4 = int_add(i2, i3)
        jump(i4, i10)
        """
        expected = """
        [i0, i10]
        i1 = int_add(i10, i0)
        i4 = int_add(i0, i1)
        jump(i4, i10)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_commutative(self):
        ops = """
        [i0, i1]
        i2 = int_add(i0, i1)
        i3 = int_add(i1, i0)
        jump(i2, i3)
        """
        expected = """
        [i0, i1]
        i2 = int_add(i0, i1)
        jump(i2, i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_ovf_commutative(self):
        ops = """
        [i0, i1]
        i2 = int_add_ovf(i0, i1)
        guard_no_overflow() []
        i3 = int_add_ovf(i1, i0)
        guard_no_overflow() []
        jump(i2, i3)
        """
        expected = """
        [i0, i1]
        i2 = int_add_ovf(i0, i1)
        guard_no_overflow() []
        jump(i2, i2)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0, i1]
        i2 = int_add_ovf(i0, i1)
        guard_no_overflow() []
        i3 = int_add(i1, i0)
        jump(i2, i3)
        """
        expected = """
        [i0, i1]
        i2 = int_add_ovf(i0, i1)
        guard_no_overflow() []
        jump(i2, i2)
        """
        self.optimize_loop(ops, expected)

    def test_addsub_const(self):
        ops = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_sub(i1, 1)
        i3 = int_add(i2, 1)
        jump(i2, i3)
        """
        expected = """
        [i0]
        i1 = int_add(i0, 1)
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_sub_constants_inverse(self):
        ops = """
        [i0, i10, i11, i12, i13]
        i2 = int_add(1, i0)
        i3 = int_add(-1, i2)
        i4 = int_sub(i0, -1)
        i5 = int_sub(i0, i2)
        jump(i0, i2, i3, i4, i5)
        """
        expected = """
        [i0, i10, i11, i12, i13]
        i2 = int_add(1, i0)
        jump(i0, i2, i0, i2, -1)
        """
        self.optimize_loop(ops, expected)
        ops = """
        [i0, i10, i11, i12, i13]
        i2 = int_add(i0, 1)
        i3 = int_add(-1, i2)
        i4 = int_sub(i0, -1)
        i5 = int_sub(i0, i2)
        jump(i0, i2, i3, i4, i5)
        """
        expected = """
        [i0, i10, i11, i12, i13]
        i2 = int_add(i0, 1)
        jump(i0, i2, i0, i2, -1)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0, i10, i11, i12, i13, i14]
        i2 = int_sub(i0, 1)
        i3 = int_add(-1, i0)
        i4 = int_add(i0, -1)
        i5 = int_sub(i2, -1)
        i6 = int_sub(i2, i0)
        jump(i0, i2, i3, i4, i5, i6)
        """
        expected = """
        [i0, i10, i11, i12, i13, i14]
        i2 = int_sub(i0, 1)
        jump(i0, i2, i2, i2, i0, -1)
        """
        self.optimize_loop(ops, expected)
        ops = """
        [i0, i10, i11, i12]
        i2 = int_add(%s, i0)
        i3 = int_add(i2, %s)
        i4 = int_sub(i0, %s)
        jump(i0, i2, i3, i4)
        """ % ((MININT, ) * 3)
        expected = """
        [i0, i10, i11, i12]
        i2 = int_add(%s, i0)
        i4 = int_sub(i0, %s)
        jump(i0, i2, i0, i4)
        """ % ((MININT, ) * 2)
        self.optimize_loop(ops, expected)

    def test_addsub_ovf(self):
        ops = """
        [i0]
        i1 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_sub_ovf(i1, 5)
        guard_no_overflow() []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_sub(i1, 5)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_subadd_ovf(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_add_ovf(i1, 5)
        guard_no_overflow() []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_sub_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_add(i1, 5)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_sub_identity(self):
        ops = """
        [i0]
        i1 = int_sub(i0, i0)
        i2 = int_sub(i1, i0)
        jump(i1, i2)
        """
        expected = """
        [i0]
        i2 = int_neg(i0)
        jump(0, i2)
        """
        self.optimize_loop(ops, expected)

    def test_shift_zero(self):
        ops = """
        [i0]
        i1 = int_lshift(0, i0)
        i2 = int_rshift(0, i0)
        i3 = int_lshift(i0, 0)
        i4 = int_rshift(i0, 0)
        jump(i1, i2, i3, i4)
        """
        expected = """
        [i0]
        jump(0, 0, i0, i0)
        """
        self.optimize_loop(ops, expected)

    def test_ushift_zero(self):
        ops = """
        [i0]
        i2 = uint_rshift(0, i0)
        i4 = uint_rshift(i0, 0)
        jump(i2, i4)
        """
        expected = """
        [i0]
        jump(0, i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_and(self):
        ops = """
        [i0]
        i1 = int_and(i0, 255)
        i2 = int_lt(i1, 500)
        guard_true(i2) []
        i3 = int_le(i1, 255)
        guard_true(i3) []
        i4 = int_gt(i1, -1)
        guard_true(i4) []
        i5 = int_ge(i1, 0)
        guard_true(i5) []
        i6 = int_lt(i1, 0)
        guard_false(i6) []
        i7 = int_le(i1, -1)
        guard_false(i7) []
        i8 = int_gt(i1, 255)
        guard_false(i8) []
        i9 = int_ge(i1, 500)
        guard_false(i9) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_and(i0, 255)
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_bug_int_and_1(self):
        ops = """
        [i51]
        i1 = int_ge(i51, 0)
        guard_true(i1) []
        i57 = int_and(i51, 1)
        i62 = int_is_zero(i57)
        guard_false(i62) []
        """
        expected = """
        [i51]
        i1 = int_le(0, i51)
        guard_true(i1) []
        i57 = int_and(i51, 1)
        i62 = int_is_zero(i57)
        guard_true(i57) []
        """
        self.optimize_loop(ops, expected)

    def test_bug_int_and_2(self):
        ops = """
        [i51]
        i1 = int_ge(i51, 0)
        guard_true(i1) []
        i57 = int_and(4, i51)
        i62 = int_is_zero(i57)
        guard_false(i62) []
        """
        expected = """
        [i51]
        i1 = int_le(0, i51)
        guard_true(i1) []
        i57 = int_and(4, i51)
        i62 = int_is_zero(i57)
        guard_false(i62) []
        """
        self.optimize_loop(ops, expected)

    def test_bug_int_or(self):
        ops = """
        [i51, i52]
        i1 = int_ge(i51, 0)
        guard_true(i1) []
        i2 = int_ge(i52, 0)
        guard_true(i2) []
        i57 = int_or(i51, i52)
        i62 = int_is_zero(i57)
        guard_false(i62) []
        """
        expected = """
        [i51, i52]
        i1 = int_le(0, i51)
        guard_true(i1) []
        i2 = int_le(0, i52)
        guard_true(i2) []
        i57 = int_or(i51, i52)
        i62 = int_is_zero(i57)
        guard_false(i62) []
        """
        self.optimize_loop(ops, expected)

    def test_int_and_positive(self):
        ops = """
        [i51, i52]
        i1 = int_ge(i51, 0)
        guard_true(i1) []
        i2 = int_ge(i52, 0)
        guard_true(i2) []

        i57 = int_and(i51, i52)
        i62 = int_lt(i57, 0)
        guard_false(i62) []
        jump(i57)
        """
        expected = """
        [i51, i52]
        i1 = int_le(0, i51)
        guard_true(i1) []
        i2 = int_le(0, i52)
        guard_true(i2) []

        i57 = int_and(i51, i52)
        jump(i57)
        """
        self.optimize_loop(ops, expected)

    def test_int_or_positive(self):
        ops = """
        [i51, i52]
        i1 = int_ge(i51, 0)
        guard_true(i1) []
        i2 = int_ge(i52, 0)
        guard_true(i2) []

        i57 = int_or(i51, i52)
        i62 = int_lt(i57, 0)
        guard_false(i62) []
        jump(i57)
        """
        expected = """
        [i51, i52]
        i1 = int_le(0, i51)
        guard_true(i1) []
        i2 = int_le(0, i52)
        guard_true(i2) []

        i57 = int_or(i51, i52)
        jump(i57)
        """
        self.optimize_loop(ops, expected)

    def test_subsub_ovf(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(1, i0)
        guard_no_overflow() []
        i2 = int_gt(i1, 1)
        guard_true(i2) []
        i3 = int_sub_ovf(1, i0)
        guard_no_overflow() []
        i4 = int_gt(i3, 1)
        guard_true(i4) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_sub_ovf(1, i0)
        guard_no_overflow() []
        i2 = int_lt(1, i1) 
        guard_true(i2) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_eq(self):
        ops = """
        [i0, i1]
        i2 = int_le(i0, 4)
        guard_true(i2) []
        i3 = int_eq(i0, i1)
        guard_true(i3) []
        i4 = int_lt(i1, 5)
        guard_true(i4) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_le(i0, 4)
        guard_true(i2) []
        i3 = int_eq(i0, i1)
        guard_true(i3) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_eq_const(self):
        ops = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_true(i1) []
        jump(10)

        """
        self.optimize_loop(ops, expected)

    def test_bound_eq_const_not(self):
        ops = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_false(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_false(i1) []
        i2 = int_add(i0, 3)
        jump(i2)

        """
        self.optimize_loop(ops, expected)

    def test_bound_ne_const(self):
        ops = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_false(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_false(i1) []
        jump(10)

        """
        self.optimize_loop(ops, expected)

    def test_bound_ne_const_not(self):
        ops = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_ltne(self):
        ops = """
        [i0, i1]
        i2 = int_lt(i0, 7)
        guard_true(i2) []
        i3 = int_ne(i0, 10)
        guard_true(i2) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_lt(i0, 7)
        guard_true(i2) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lege_const(self):
        ops = """
        [i0]
        i1 = int_ge(i0, 7)
        guard_true(i1) []
        i2 = int_le(i0, 7)
        guard_true(i2) []
        i3 = int_add(i0, 3)
        jump(i3)
        """
        expected = """
        [i0]
        i1 = int_le(7, i0)
        guard_true(i1) []
        i2 = int_eq(i0, 7)
        guard_true(i2) []
        jump(10)

        """
        self.optimize_loop(ops, expected)

    def test_mul_ovf(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_lt(i1, 5)
        guard_true(i3) []
        i4 = int_gt(i1, -10)
        guard_true(i4) []
        i5 = int_mul_ovf(i2, i1)
        guard_no_overflow() []
        i6 = int_lt(i5, -2550)
        guard_false(i6) []
        i7 = int_ge(i5, 1276)
        guard_false(i7) []
        i8 = int_gt(i5, 126)
        guard_true(i8) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_lt(i1, 5)
        guard_true(i3) []
        i4 = int_gt(i1, -10)
        guard_true(i4) []
        i5 = int_mul(i2, i1)
        i8 = int_gt(i5, 126)
        guard_true(i8) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)


    def test_sub_ovf_before(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_sub_ovf(i2, i1)
        guard_no_overflow() []
        i4 = int_le(i3, 10)
        guard_true(i4) []
        i5 = int_ge(i3, 2)
        guard_true(i5) []
        i6 = int_lt(i1, -10)
        guard_false(i6) []
        i7 = int_gt(i1, 253)
        guard_false(i7) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_sub_ovf(i2, i1)
        guard_no_overflow() []
        i4 = int_le(i3, 10)
        guard_true(i4) []
        i5 = int_ge(i3, 2)
        guard_true(i5) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_true_bounds(self):
        ops = """
        [i0]
        i12 = int_ge(i0, 0)
        guard_true(i12) []
        i1 = int_is_true(i0)
        guard_true(i1) []
        i2 = int_ge(0, i0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i12 = int_le(0, i0)
        guard_true(i12) []
        i1 = int_is_true(i0)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_zero_bounds(self):
        ops = """
        [i0]
        i12 = int_ge(i0, 0)
        guard_true(i12) []
        i1 = int_is_zero(i0)
        guard_false(i1) []
        i2 = int_ge(0, i0)
        guard_false(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i12 = int_le(0, i0)
        guard_true(i12) []
        i1 = int_is_zero(i0)
        guard_false(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_or_same_arg(self):
        ops = """
        [i0]
        i1 = int_or(i0, i0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_xor_same_arg(self):
        ops = """
        [i0]
        i1 = int_xor(i0, i0)
        jump(i1)
        """
        expected = """
        [i0]
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_fold_partially_constant_xor(self):
        ops = """
        [i0, i1]
        i2 = int_xor(i0, 23)
        i3 = int_xor(i1, 0)
        jump(i2, i3)
        """
        expected = """
        [i0, i1]
        i2 = int_xor(i0, 23)
        jump(i2, i1)
        """
        self.optimize_loop(ops, expected)

    # ______________________________________________________

    def test_intand_1mask_covering_bitrange(self):
        ops = """
        [i0]
        i0pos = int_ge(i0, 0)
        guard_true(i0pos) []
        i0small = int_lt(i0, 256)
        guard_true(i0small) []
        i1 = int_and(i0, 255)
        i2 = int_and(i1, -1)
        i3 = int_and(511, i2)
        jump(i3)
        """

        expected = """
        [i0]
        i0pos = int_le(0, i0)
        guard_true(i0pos) []
        i0small = int_lt(i0, 256)
        guard_true(i0small) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_intand_maskwith0_in_bitrange(self):
        ops = """
        [i0, i2]
        i0pos = int_le(0, i0)
        guard_true(i0pos) []
        i0small = int_lt(i0, 256)
        guard_true(i0small) []

        i1 = int_and(i0, 257)

        i2pos = int_le(0, i2)
        guard_true(i2pos) []
        i2small = int_lt(i2, 256)
        guard_true(i2small) []

        i3 = int_and(259, i2)
        jump(i1, i3)
        """
        self.optimize_loop(ops, ops)

    i0_range_256_i1_range_65536_prefix = """
        [i0, i1]
        i0pos = int_le(0, i0)
        guard_true(i0pos) []
        i0small = int_lt(i0, 256)
        guard_true(i0small) []

        i1pos = int_le(0, i1)
        guard_true(i1pos) []
        i1small = int_lt(i1, 65536)
        guard_true(i1small) []
    """

    def test_int_and_cmp_above_bounds(self):

        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_and(i0, i1)
        i3 = int_le(i2, 255)
        guard_true(i3) []
        jump(i2)
        """

        expected = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_and(i0, i1)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_and_cmp_below_bounds(self):
        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_and(i0, i1)
        i3 = int_lt(i2, 255)
        guard_true(i3) []
        jump(i2)
        """
        self.optimize_loop(ops, ops)

    def test_int_and_positive(self):
        ops = """
        [i0, i1]
        i2 = int_ge(i1, 0)
        guard_true(i2) []
        i3 = int_and(i0, i1)
        i4 = int_ge(i3, 0)
        guard_true(i4) []
        jump(i3)
        """
        expected = """
        [i0, i1]
        i2 = int_le(0, i1)
        guard_true(i2) []
        i3 = int_and(i0, i1)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_or_cmp_above_bounds(self):
        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_or(i0, i1)
        i3 = int_le(i2, 65535)
        guard_true(i3) []
        jump(i2)
        """

        expected = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_or(i0, i1)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_or_cmp_below_bounds(self):
        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_or(i0, i1)
        i3 = int_lt(i2, 65535)
        guard_true(i3) []
        jump(i2)
        """
        self.optimize_loop(ops, ops)

    def test_int_xor_cmp_above_bounds(self):
        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_xor(i0, i1)
        i3 = int_le(i2, 65535)
        guard_true(i3) []
        jump(i2)
        """

        expected = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_xor(i0, i1)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_xor_cmp_below_bounds(self):
        ops = self.i0_range_256_i1_range_65536_prefix + """
        i2 = int_xor(i0, i1)
        i3 = int_lt(i2, 65535)
        guard_true(i3) []
        jump(i2)
        """
        self.optimize_loop(ops, ops)

    def test_int_xor_positive_is_positive(self):
        ops = """
        [i0, i1]
        i2 = int_lt(i0, 0)
        guard_false(i2) []
        i3 = int_lt(i1, 0)
        guard_false(i3) []
        i4 = int_xor(i0, i1)
        i5 = int_lt(i4, 0)
        guard_false(i5) []
        jump(i4, i0)
        """
        expected = """
        [i0, i1]
        i2 = int_lt(i0, 0)
        guard_false(i2) []
        i3 = int_lt(i1, 0)
        guard_false(i3) []
        i4 = int_xor(i0, i1)
        jump(i4, i0)
        """
        self.optimize_loop(ops, expected)

    def test_positive_rshift_bits_minus_1(self):
        ops = """
        [i0]
        i2 = int_lt(i0, 0)
        guard_false(i2) []
        i3 = int_rshift(i2, %d)
        jump(i3)
        """ % (LONG_BIT - 1,)
        expected = """
        [i0]
        i2 = int_lt(i0, 0)
        guard_false(i2) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_int_invert(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = int_invert(i0)
        i3 = int_lt(i2, 0)
        guard_true(i3) []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = int_invert(i0)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_invert_invert(self):
        ops = """
        [i1]
        i2 = int_invert(i1)
        i3 = int_invert(i2)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_invert(i1)
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_invert_postprocess(self):
        ops = """
        [i1]
        i2 = int_invert(i1)
        i3 = int_lt(i2, 0)
        guard_true(i3) []
        i4 = int_ge(i1, 0)
        guard_true(i4) []
        jump(i2)
        """
        expected = """
        [i1]
        i2 = int_invert(i1)
        i3 = int_lt(i2, 0)
        guard_true(i3) []
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_neg(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = int_neg(i0)
        i3 = int_le(i2, 0)
        guard_true(i3) []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = int_neg(i0)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_neg_postprocess(self):
        ops = """
        [i1]
        i2 = int_neg(i1)
        i3 = int_ge(i2, 0)
        guard_true(i3) []
        i4 = int_le(i1, 0)
        guard_true(i4) []
        jump(i1)
        """
        expected = """
        [i1]
        i2 = int_neg(i1)
        i3 = int_le(0, i2)
        guard_true(i3) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_signext_already_in_bounds(self):
        ops = """
        [i0]
        i1 = int_signext(i0, 1)
        i2 = int_signext(i1, 2)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_signext(i0, 1)
        jump(i1)
        """
        self.optimize_loop(ops, expected)
        #
        ops = """
        [i0]
        i1 = int_signext(i0, 1)
        i2 = int_signext(i1, 1)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_signext(i0, 1)
        jump(i1)
        """
        self.optimize_loop(ops, expected)
        #
        ops = """
        [i0]
        i1 = int_signext(i0, 2)
        i2 = int_signext(i1, 1)
        jump(i2)
        """
        self.optimize_loop(ops, ops)

    def test_bound_backpropagate_int_signext(self):
        ops = """
        [i0]
        i1 = int_signext(i0, 1)
        i2 = int_eq(i0, i1)
        guard_true(i2) []
        i3 = int_le(i0, 127)    # implied by equality with int_signext
        guard_true(i3) []
        i5 = int_gt(i0, -129)   # implied by equality with int_signext
        guard_true(i5) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_signext(i0, 1)
        i2 = int_eq(i0, i1)
        guard_true(i2) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_backpropagate_int_signext_2(self):
        ops = """
        [i0]
        i1 = int_signext(i0, 1)
        i2 = int_eq(i0, i1)
        guard_true(i2) []
        i3 = int_le(i0, 126)    # false for i1 == 127
        guard_true(i3) []
        i5 = int_lt(-128, i0)   # false for i1 == -128
        guard_true(i5) []
        jump(i1)
        """
        self.optimize_loop(ops, ops)

    def test_uint_mul_high_constfold(self):
        ops = """
        [i0]
        i1 = int_lshift(254, %s)
        i2 = int_lshift(171, %s)
        i3 = uint_mul_high(i1, i2)
        jump(i3)
        """ % (LONG_BIT // 2, LONG_BIT // 2)
        expected = """
        [i0]
        jump(43434)
        """
        self.optimize_loop(ops, expected)

    def test_mul_ovf_before_bug(self):
        ops = """
        [i0]
        i3 = int_mul(i0, 12)
        guard_value(i3, 12) []
        jump(i0)
        """
        self.optimize_loop(ops, ops)

    def test_lshift_before_bug(self):
        ops = """
        [i0]
        i3 = int_lshift(%s, i0)

        i1 = int_lt(i0, 16)
        guard_true(i1) []
        i2 = int_le(0, i0)
        guard_true(i2) []

        guard_value(i3, 0) []
        jump(i0)
        """ % (1 << (LONG_BIT - 3))
        self.optimize_loop(ops, ops)

    def test_knownbits_int_or_and(self):
        ops = """
        [i1]
        i2 = int_or(i1, 1)
        i3 = int_and(i2, 1)
        escape_i(i3)
        jump(i1)
        """
        expected = """
        [i1]
        i2 = int_or(i1, 1)
        escape_i(1)
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_uint_rshift(self):
        ops = """
        [i1]
        i2 = uint_rshift(i1, %s)
        i3 = int_and(i2, 14)
        i4 = int_is_zero(i3)
        guard_true(i4) []
        jump(i1)
        """ % (LONG_BIT - 1, )
        expected = """
        [i1]
        i2 = uint_rshift(i1, %s)
        jump(i1)
        """ % (LONG_BIT - 1, )
        self.optimize_loop(ops, expected)

    def test_knownbits_int_rshift_not_optimizable(self):
        ops = """
        [i1]
        i2 = uint_rshift(i1, 512)
        i3 = int_is_zero(i2)
        guard_true(i3) []         # <- this should vanish
        i4 = int_rshift(i1, 512)
        i5 = int_is_zero(i4)      # <- but we cant know this!
        guard_true(i5) []
        """
        expected = """
        [i1]
        i4 = int_rshift(i1, 512)
        i5 = int_is_zero(i4)      # <- would still be there
        guard_true(i5) []
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_int_rshift_optimizable(self):
        ops = """
        [i1]
        i2 = uint_rshift(i1, 512)
        i3 = int_is_zero(i2)
        guard_true(i3) []         # <- this should vanish
        i4 = int_rshift(i1, 512)
        i5 = int_is_zero(i4)      # <- but we cant know this!
        guard_true(i5) []
        """
        expected = """
        [i1]
        i4 = int_rshift(i1, 512)
        i5 = int_is_zero(i4)      # <- ... so it will still be there
        guard_true(i5) []
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_uint_rshift_and_backwards(self):
        ops = """
        [i262]
        i268 = uint_rshift(i262, 2)
        i270 = int_and(i268, 1)
        guard_false(i270) []
        i4 = int_and(i262, 4)
        guard_false(i4) []
        jump(i262)
        """
        expected = """
        [i262]
        i268 = uint_rshift(i262, 2)
        i270 = int_and(i268, 1)
        guard_false(i270) []
        jump(i262)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_int_rshift_and_backwards(self):
        ops = """
        [i262]
        i268 = int_rshift(i262, 2)
        i270 = int_and(i268, 1)
        guard_false(i270) []
        i4 = int_and(i262, 4)
        guard_false(i4) []
        jump(i262)
        """
        expected = """
        [i262]
        i268 = int_rshift(i262, 2)
        i270 = int_and(i268, 1)
        guard_false(i270) []
        jump(i262)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_and_backwards_nonconst(self):
        ops = """
        [i1, i2]
        i3 = int_or(i1, 255)
        i5 = int_and(i3, i2)
        guard_value(i5, 509) []
        i6 = int_and(i2, 7)
        guard_value(i6, 5) []
        jump(i1)
        """
        expected = """
        [i1, i2]
        i3 = int_or(i1, 255)
        i5 = int_and(i3, i2)
        guard_value(i5, 509) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_and_backwards_result_nonconst(self):
        ops = """
        [i1, i2]
        i3 = int_or(i1, 255)
        i4 = int_and(i2, 1023)
        i5 = int_and(i3, i4)
        i6 = int_lt(i5, 128)
        guard_true(i6) []
        i7 = int_lt(i4, 900)
        guard_true(i7) []
        jump(i4)
        """
        expected = """
        [i1, i2]
        i3 = int_or(i1, 255)
        i4 = int_and(i2, 1023)
        i5 = int_and(i3, i4)
        i6 = int_lt(i5, 128)
        guard_true(i6) []
        jump(i4)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_goal_alignment_simple_sub(self):
        ops = """
        [i0]
        ic0 = int_invert(3)
        i1 = int_and(i0, ic0)
        i4 = int_and(i1, 1)
        i5 = int_is_zero(i4)
        guard_true(i5) []
        i6 = int_sub(i1, 8)
        i7 = int_and(i6, 3)
        i8 = int_is_zero(i7)
        guard_true(i8) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_and(i0, -4)
        i6 = int_sub(i1, 8)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_goal_alignment_simple_add(self):
        ops = """
        [i0]
        ic0 = int_invert(3)
        i1 = int_and(i0, ic0)
        i4 = int_and(i1, 1)
        i5 = int_is_zero(i4)
        guard_true(i5) []
        i6 = int_add(i1, 8)
        i7 = int_and(i6, 3)
        i8 = int_is_zero(i7)
        guard_true(i8) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_and(i0, -4)
        i6 = int_add(i1, 8)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_goal_alignment_final(self):
        ops = """
        [i1]
        i2 = int_and(i1, 3)
        i3 = int_is_zero(i2)
        guard_true(i3) []
        i4 = int_and(i1, 1)
        i5 = int_is_zero(i4)
        guard_true(i5) []
        i6 = int_add(i1, 8)
        i7 = int_and(i6, 3)
        i8 = int_is_zero(i7)
        guard_true(i8) []
        jump(i6)
        """
        expected = """
        [i1]
        i2 = int_and(i1, 3)
        i3 = int_is_zero(i2)
        guard_true(i3) []
        i6 = int_add(i1, 8)
        jump(i6)
        """
        self.optimize_loop(ops, expected)

    @pytest.mark.skipif("LONG_BIT != 64")
    def test_higher_bits_known(self):
        ops = """
        [i40]
        i42 = int_le(2147487760, i40)            # range check: inside RAM
        guard_true(i42) []
        i44 = int_lt(i40, 2214592511)
        guard_true(i44) []
        i46 = int_and(i40, -9223372036854775808) # uppermost bit cannot be set
        i47 = int_is_true(i46)
        guard_false(i47) []
        jump(i40)
        """
        expected = """
        [i40]
        i42 = int_le(2147487760, i40)            # range check: inside RAM
        guard_true(i42) []
        i44 = int_lt(i40, 2214592511)
        guard_true(i44) []
        jump(i40)
        """
        self.optimize_loop(ops, expected)

    def test_bug_dont_use_getint(self):
        ops = """
        [i1, i2]
        i45 = int_xor(i1, i2) # 0
        i163 = int_neg(i45) # 0
        guard_value(i163, 0) []
        i228 = int_add(1, i2)
        i318 = uint_rshift(i228, 0) # == i288
        i404 = int_add(i318, i45)
        finish(i404)
        """
        expected = """
        [i1, i2]
        i45 = int_xor(i1, i2) # 0
        i163 = int_neg(i45) # 0
        guard_value(i163, 0) []
        i404 = int_add(1, i2)
        finish(i404)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lshift_result_unbounded(self):
        # bounded_above << bounded
        ops = """
        [i1, i2, i3]
        i4 = int_lt(i1, 7) # i1 < 7
        guard_true(i4) []

        i5 = int_lt(i3, 2) # i3 == 0 or i3 == 1
        guard_true(i5) []
        i6 = int_le(0, i3)
        guard_true(i6) []

        i7 = int_lshift(i1, i3)
        i8 = int_le(i7, 14)
        guard_true(i8) [] # can't be removed
        i8b = int_lshift(i1, i2)
        i9 = int_le(i8b, 14) # can't be removed
        guard_true(i9) []
        jump(i1, i2, i3)
        """
        self.optimize_loop(ops, ops)

        # bounded << unbounded
        ops = """
        [i1b, i2]
        i4b = int_lt(i1b, 7) # 0 <= i1b < 7
        guard_true(i4b) []
        i4c = int_le(0, i1b)
        guard_true(i4c) []

        i15 = int_lshift(i1b, i2)
        i16 = int_le(i15, 14)
        guard_true(i16) []
        jump(i1b, i2)
        """
        self.optimize_loop(ops, ops)

    def test_bound_lshift(self):
        ops = """
        [i1b, i3]
        i4b = int_lt(i1b, 7) # 0 <= i1b < 7
        guard_true(i4b) []
        i4c = int_ge(i1b, 0)
        guard_true(i4c) []

        i5 = int_lt(i3, 2) # i3 == 0 or i3 == 1
        guard_true(i5) []
        i6 = int_ge(i3, 0)
        guard_true(i6) []

        i13 = int_lshift(i1b, i3)
        i14 = int_le(i13, 14) # removed
        guard_true(i14) [] # removed
        jump(i1b, i3)
        """
        expected = """
        [i1b, i3]
        i4b = int_lt(i1b, 7)
        guard_true(i4b) []
        i4c = int_le(0, i1b)
        guard_true(i4c) []

        i5 = int_lt(i3, 2)
        guard_true(i5) []
        i6 = int_le(0, i3)
        guard_true(i6) []

        i13 = int_lshift(i1b, i3)
        jump(i1b, i3)
        """
        self.optimize_loop(ops, expected)

    def test_bound_lshift_backwards(self):
        ops = """
        [i0, i3]
        i5 = int_lt(i3, 2) # i3 == 0 or i3 == 1
        guard_true(i5) []
        i6 = int_ge(i3, 0)
        guard_true(i6) []

        i10 = int_lshift(i0, i3)
        i11 = int_le(i10, 14)
        guard_true(i11) []
        i12 = int_lt(i0, 15) # used to be removed, but that's wrong
        guard_true(i12) []

        jump(i0, i3)
        """
        expected = """
        [i0, i3]

        i5 = int_lt(i3, 2)
        guard_true(i5) []
        i6 = int_le(0, i3)
        guard_true(i6) []

        i10 = int_lshift(i0, i3)
        i11 = int_le(i10, 14)
        guard_true(i11) []
        i12 = int_lt(i0, 15) # used to be removed, but that's wrong
        guard_true(i12) []

        jump(i0, i3)
        """
        self.optimize_loop(ops, expected)

    def test_bound_rshift_result_unbounded(self):
        # unbounded >> bounded
        ops = """
        [i0, i3]
        i5 = int_lt(i3, 2) # i3 == 0 or i3 == 1
        guard_true(i5) []
        i6 = int_le(0, i3)
        guard_true(i6) []

        i10 = int_rshift(i0, i3)
        i11 = int_le(i10, 14)
        guard_true(i11) []
        i12 = int_lt(i0, 25)
        guard_true(i12) []
        jump(i0, i3)
        """
        self.optimize_loop(ops, ops)

    def test_bound_rshift(self):
        ops = """
        [i1, i1b, i2, i3]
        i4 = int_lt(i1, 7) # i1 < 7
        guard_true(i4) []

        i4b = int_lt(i1b, 7) # 0 <= i1b < 7
        guard_true(i4b) []
        i4c = int_ge(i1b, 0)
        guard_true(i4c) []

        i5 = int_lt(i3, 2) # i3 == 0 or i3 == 1
        guard_true(i5) []
        i6 = int_ge(i3, 0)
        guard_true(i6) []

        i7 = int_rshift(i1, i3)
        i8 = int_le(i7, 14) # removed
        guard_true(i8) [] # removed
        i8b = int_rshift(i1, i2)
        i9 = int_le(i8b, 14)
        guard_true(i9) []

        i13 = int_rshift(i1b, i3)
        i14 = int_le(i13, 14) # removed
        guard_true(i14) [] # removed
        i15 = int_rshift(i1b, i2)
        i16 = int_le(i15, 14)
        guard_true(i16) []
        jump(i1, i1b, i2, i3)
        """
        expected = """
        [i1, i1b, i2, i3]
        i4 = int_lt(i1, 7)
        guard_true(i4) []

        i4b = int_lt(i1b, 7)
        guard_true(i4b) []
        i4c = int_le(0, i1b)
        guard_true(i4c) []

        i5 = int_lt(i3, 2)
        guard_true(i5) []
        i6 = int_le(0, i3)
        guard_true(i6) []

        i7 = int_rshift(i1, i3)
        i8b = int_rshift(i1, i2)
        i9 = int_le(i8b, 14)
        guard_true(i9) []

        i13 = int_rshift(i1b, i3)
        i15 = int_rshift(i1b, i2)
        i16 = int_le(i15, 14)
        guard_true(i16) []
        jump(i1, i1b, i2, i3)
        """
        self.optimize_loop(ops, expected)

    def test_pure_ovf_bug_simple(self):
        ops = """
        [i1, i2]
        i3 = int_add(i2, i1)
        i4 = int_add_ovf(i2, i1)
        guard_no_overflow() []
        jump(i4)
        """
        self.optimize_loop(ops, ops)

    def test_pure_ovf_bug_with_arithmetic_rewrites(self):
        ops = """
        [i1, i2]
        i3 = int_add_ovf(i1, i2)
        guard_no_overflow() []
        i4 = int_sub_ovf(i3, i2)
        guard_no_overflow() []
        jump(i4)
        """
        self.optimize_loop(ops, ops)

    def test_pure_ovf_bug_with_replacement(self):
        ops = """
        [i0, i1, i11]
        i2 = int_sub_ovf(i0, i1)
        guard_no_overflow() []
        i3 = int_add(i2, i11)
        i4 = int_sub_ovf(i3, i11)
        guard_no_overflow() []
        jump(i4)
        """
        result = """
        [i0, i1, i11]
        i2 = int_sub_ovf(i0, i1)
        guard_no_overflow() []
        i3 = int_add(i2, i11)
        jump(i2)
        """
        self.optimize_loop(ops, ops)

    def test_intdiv_bounds(self):
        ops = """
        [i0, i1]
        i4 = int_ge(i1, 3)
        guard_true(i4) []
        i2 = call_pure_i(321, i0, i1, descr=int_py_div_descr)
        i3 = int_add_ovf(i2, 50)
        guard_no_overflow() []
        jump(i3, i1)
        """
        expected = """
        [i0, i1]
        i4 = int_le(3, i1)
        guard_true(i4) []
        i2 = call_i(321, i0, i1, descr=int_py_div_descr)
        i3 = int_add(i2, 50)
        jump(i3, i1)
        """
        self.optimize_loop(ops, expected)

    def test_intmod_bounds(self):
        ops = """
        [i0, i1]
        i2 = call_pure_i(321, i0, 12, descr=int_py_mod_descr)
        i3 = int_ge(i2, 12)
        guard_false(i3) []
        i4 = int_lt(i2, 0)
        guard_false(i4) []
        i5 = call_pure_i(321, i1, -12, descr=int_py_mod_descr)
        i6 = int_le(i5, -12)
        guard_false(i6) []
        i7 = int_gt(i5, 0)
        guard_false(i7) []
        jump(i2, i5)
        """
        kk, ii = magic_numbers(12)
        expected = """
        [i0, i1]
        i4 = int_rshift(i0, %d)
        i6 = int_xor(i0, i4)
        i8 = uint_mul_high(i6, %d)
        i9 = uint_rshift(i8, %d)
        i10 = int_xor(i9, i4)
        i11 = int_mul(i10, 12)
        i2 = int_sub(i0, i11)
        i5 = call_i(321, i1, -12, descr=int_py_mod_descr)
        jump(i2, i5)
        """ % (63 if MAXINT > 2**32 else 31, intmask(kk), ii)
        self.optimize_loop(ops, expected)

    def test_intmod_bounds2(self):
        # same as above (2nd case), but all guards are shifted by one so
        # that they must stay
        ops = """
        [i9, i1]
        i5 = call_pure_i(321, i1, -12, descr=int_py_mod_descr)
        i6 = int_le(i5, -11)
        guard_false(i6) []
        i7 = int_lt(-1, i5)
        guard_false(i7) []
        jump(i5)
        """
        self.optimize_loop(ops, ops.replace('call_pure_i', 'call_i'))

    def test_intmod_bounds_bug1(self):
        ops = """
        [i0]
        i1 = call_pure_i(321, i0, %d, descr=int_py_mod_descr)
        i2 = int_is_zero(i1)
        guard_false(i2) []
        finish()
        """ % (-(1<<(LONG_BIT-1)),)
        self.optimize_loop(ops, ops.replace('call_pure_i', 'call_i'))


    def test_intmod_pow2(self):
        # 'n % power-of-two' can always be turned into int_and(), even
        # if n is possibly negative.  That's by we handle 'int_py_mod'
        # and not C-like mod.
        ops = """
        [i0]
        i1 = call_pure_i(321, i0, 8, descr=int_py_mod_descr)
        finish(i1)
        """
        expected = """
        [i0]
        i1 = int_and(i0, 7)
        finish(i1)
        """
        self.optimize_loop(ops, expected)

    def test_unsigned_comparisons_zero(self):
        ops = """
        [i0]
        i1 = uint_lt(i0, 0)
        guard_false(i1) []
        i2 = uint_gt(0, i0)
        guard_false(i2) []
        i3 = uint_le(0, i0)
        guard_true(i3) []
        i4 = uint_ge(i0, 0)
        guard_true(i4) []
        finish()
        """
        expected = """
        [i0]
        finish()
        """
        self.optimize_loop(ops, expected)

    def test_int_and_knownbits_bounds_agreement_bug(self):
        ops = """
        [i1]
        i3 = int_and(i1, -27)
        guard_value(i3, 5) []
        i4 = int_ge(i1, 3)
        guard_true(i4) []
        i5 = int_le(i1, 9)
        guard_true(i5) []
        i6 = int_and(i1, -44)
        guard_value(i6, 4) []
        jump()
        """
        expected = """
        [i1]
        i3 = int_and(i1, -27)
        guard_value(i3, 5) []
        i5 = int_le(i1, 9)
        guard_true(i5) []
        jump()
        """
        self.optimize_loop(ops, expected) # used to crash

    def test_not_enough_intbound_shrinking_bug(self):
        ops = """
        [i1]
        i4 = int_mul_ovf(i1, 15)
        guard_no_overflow() []
        i41616 = int_le(i1, 27)
        guard_true(i41616) []
        i41620 = int_and(i1, 23)
        guard_value(i41620, 7) []
        i41613 = int_le(i1, i4)
        guard_false(i41613) []
        jump()
        """
        self.optimize_loop(ops, ops) # used to crash

    def test_int_is_true_nonpositive(self):
        ops = """
        [i75]
        i77 = int_and(i75, %s)
        i78 = int_is_true(i77)
        guard_true(i78) []
        i80 = uint_gt(i75, 0)
        guard_true(i80) []
        i84 = uint_rshift(i75, %s)
        guard_true(i84) []
        jump()
        """ % (MININT, LONG_BIT - 1)
        expected = """
        [i75]
        i77 = int_and(i75, %s)
        i78 = int_is_true(i77)
        guard_true(i78) []
        jump()
        """ % MININT
        self.optimize_loop(ops, expected)

    def test_intdiv_pow2(self):
        ops1 = """
        [i0, i1]
        i6 = int_ge(i0, 0)
        guard_true(i6) []
        i7 = int_lt(i0, %s)
        guard_true(i7) []
        i3 = int_lshift(1, i0)
        i4 = call_pure_i(321, i1, i3, descr=int_py_div_descr)
        jump(i4)
        """ % (LONG_BIT - 1, )
        expected1 = """
        [i0, i1]
        i6 = int_le(0, i0)
        guard_true(i6) []
        i7 = int_lt(i0, %s)
        guard_true(i7) []
        i3 = int_lshift(1, i0)
        i4 = int_rshift(i1, i0)
        jump(i4)
        """ % (LONG_BIT - 1, )
        ops2 = """
        [i0, i1]
        i2 = int_and(i0, %s)
        i3 = int_lshift(1, i2)
        i4 = call_i(321, i1, i3, descr=int_py_div_descr)
        jump(i4)
        """ % (LONG_BIT - 1, )
        self.optimize_loop(ops1, expected1)
        self.optimize_loop(ops2, ops2)

    def test_knownbits_equality(self):
        ops = """
        [i0, i1]
        i2 = int_or(i0, 3) # set lowest three bits
        i3 = int_and(i1, 252) # unset lowest two bits
        i4 = int_eq(i2, i3)
        guard_false(i4) []
        jump(i2)
        """
        expected = """
        [i0, i1]
        i2 = int_or(i0, 3) # set lowest three bits
        i3 = int_and(i1, 252) # unset lowest two bits
        jump(i2)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0, i1]
        i2 = int_or(i0, 3) # set lowest three bits
        i3 = int_and(i1, 252) # unset lowest two bits
        i4 = int_ne(i2, i3)
        guard_true(i4) []
        jump(i2)
        """
        expected = """
        [i0, i1]
        i2 = int_or(i0, 3) # set lowest three bits
        i3 = int_and(i1, 252) # unset lowest two bits
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_or_has_const_result(self):
        ops = """
        [i1]
        i2 = int_and(i1, 255)
        i3 = int_or(i2, 255)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_and(i1, 255)
        jump(255)
        """
        self.optimize_loop(ops, expected)

    def test_int_invert_postprocess_further(self):
        ops = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_invert(i1)
        i3 = int_lt(i2, 100)
        guard_true(i3) []
        i4 = int_gt(i0, -1000)
        guard_true(i4) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_invert(i1)
        i3 = int_lt(i2, 100)
        guard_true(i3) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_neg_postprocess_further(self):
        ops = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_neg(i1)
        i3 = int_gt(i2, 100)
        guard_true(i3) []
        i4 = int_lt(i0, 0)
        guard_true(i4) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_neg(i1)
        i3 = int_lt(100, i2)
        guard_true(i3) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_xor(self):
        # this also checks backwards propagation or xor
        ops = """
        [i0, i1, i2]
        it1 = int_ge(i1, 0)
        guard_true(it1) []
        it2 = int_gt(i2, 0)
        guard_true(it2) []
        ix1 = int_xor(i0, i0)
        ix1t = int_ge(ix1, 0)
        guard_true(ix1t) []
        ix2 = int_xor(i0, i1)
        ix2t = int_ge(ix2, 0)
        guard_true(ix2t) []
        ix3 = int_xor(i1, i0)
        ix3t = int_ge(ix3, 0)
        guard_true(ix3t) []
        ix4 = int_xor(i1, i2)
        ix4t = int_ge(ix4, 0)
        guard_true(ix4t) []
        jump(i0, i1, i2)
        """
        expected = """
        [i0, i1, i2]
        it1 = int_le(0, i1)
        guard_true(it1) []
        it2 = int_lt(0, i2)
        guard_true(it2) []
        ix2 = int_xor(i0, i1)
        ix2t = int_le(0, ix2)
        guard_true(ix2t) []
        ix4 = int_xor(i1, i2)
        jump(i0, i1, i2)
        """
        self.optimize_loop(ops, expected)

    def test_knownbits_or_backwards(self):
        ops = """
        [i1]
        i3 = int_or(i1, 7)
        guard_value(i3, 15) []
        i4 = int_and(i1, 8)
        i5 = int_is_true(i4)
        guard_true(i5) []
        jump(i1)
        """
        expected = """
        [i1]
        i3 = int_or(i1, 7)
        guard_value(i3, 15) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    @pytest.mark.skipif("LONG_BIT != 64")
    def test_bool_rewriting_crash(self):
        ops = """
        [i34, i35, i36]
        i37 = int_is_zero(i34)
        i38 = int_lt(i36, i37)
        i39 = int_neg(i35)
        i40 = int_le(i34, 17)
        guard_true(i40)[]
        i41 = int_sub_ovf(i37, i37)
        guard_no_overflow() []
        i42 = int_ge(i34, -7)
        guard_true(i42) []
        i43 = int_and(i35, 0)
        guard_value(i43, 0) []
        i44 = int_le(i41, 17)
        guard_true(i44) []
        i45 = int_le(i35, i37)
        i46 = int_ne(i39, i41)
        i47 = int_or(i39, i46)
        i48 = int_is_true(i34)
        guard_false(i48) []
        guard_true(i46) []
        i49 = int_and(i39, -24)
        guard_value(i49, 4611686018427387904) []
        i50 = int_ne(i41, i39)
        finish()
        """
        expected = """
        [i34, i35, i36]
        i37 = int_is_zero(i34)
        i38 = int_lt(i36, i37)
        i39 = int_neg(i35)
        i40 = int_le(i34, 17)
        guard_true(i40)[]
        i42 = int_le(-7, i34)
        guard_true(i42) []
        i45 = int_le(i35, i37)
        i46 = int_is_true(i39)
        i47 = int_or(i39, i46)
        i48 = int_is_true(i34)
        guard_false(i48) []
        guard_true(i46) []
        i49 = int_and(i39, -24)
        guard_value(i49, 4611686018427387904) []
        finish()
        """
        self.optimize_loop(ops, expected)

    def test_addsub_ovf(self):
        ops = """
        [i0]
        i1 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_sub_ovf(i1, 5)
        guard_no_overflow() []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_add_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_sub(i1, 5)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_subadd_ovf(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_add_ovf(i1, 5)
        guard_no_overflow() []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_sub_ovf(i0, 10)
        guard_no_overflow() []
        i2 = int_add(i1, 5)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_and(self):
        ops = """
        [i0]
        i1 = int_and(i0, 255)
        i2 = int_lt(i1, 500)
        guard_true(i2) []
        i3 = int_le(i1, 255)
        guard_true(i3) []
        i4 = int_gt(i1, -1)
        guard_true(i4) []
        i5 = int_ge(i1, 0)
        guard_true(i5) []
        i6 = int_lt(i1, 0)
        guard_false(i6) []
        i7 = int_le(i1, -1)
        guard_false(i7) []
        i8 = int_gt(i1, 255)
        guard_false(i8) []
        i9 = int_ge(i1, 500)
        guard_false(i9) []
        i12 = int_lt(i1, 100)
        guard_true(i12) []
        i13 = int_le(i1, 90)
        guard_true(i13) []
        i14 = int_gt(i1, 10)
        guard_true(i14) []
        i15 = int_ge(i1, 20)
        guard_true(i15) []
        jump()
        """
        expected = """
        [i0]
        i1 = int_and(i0, 255)
        i12 = int_lt(i1, 100)
        guard_true(i12) []
        i13 = int_le(i1, 90)
        guard_true(i13) []
        i14 = int_lt(10, i1)
        guard_true(i14) []
        i15 = int_le(20, i1)
        guard_true(i15) []
        jump()
        """
        self.optimize_loop(ops, expected)

    def test_bound_floordiv(self):
        ops = """
        [i0, i1, i2]
        it1 = int_ge(i1, 0)
        guard_true(it1) []
        it2 = int_gt(i2, 0)
        guard_true(it2) []
        ix2 = call_pure_i(321, i0, i1, descr=int_py_div_descr)
        ix2t = int_ge(ix2, 0)
        guard_true(ix2t) []
        ix3 = call_pure_i(321, i1, i0, descr=int_py_div_descr)
        ix3t = int_ge(ix3, 0)
        guard_true(ix3t) []
        ix4 = call_pure_i(321, i1, i2, descr=int_py_div_descr)
        ix4t = int_ge(ix4, 0)
        guard_true(ix4t) []
        jump(i0, i1, i2)
        """
        expected = """
        [i0, i1, i2]
        it1 = int_le(0, i1)
        guard_true(it1) []
        it2 = int_lt(0, i2)
        guard_true(it2) []
        ix2 = call_i(321, i0, i1, descr=int_py_div_descr)
        ix2t = int_le(0, ix2)
        guard_true(ix2t) []
        ix3 = call_i(321, i1, i0, descr=int_py_div_descr)
        ix3t = int_le(0, ix3)
        guard_true(ix3t) []
        ix4 = call_i(321, i1, i2, descr=int_py_div_descr)
        # <== the check that ix4 is nonnegative was removed
        jump(i0, i1, i2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_int_is_zero(self):
        ops = """
        [i1, i2a, i2b, i2c]
        i3 = int_is_zero(i1)
        i4 = int_gt(i2a, 7)
        guard_true(i4) []
        i5 = int_is_zero(i2a)
        guard_false(i5) []
        i6 = int_le(i2b, -7)
        guard_true(i6) []
        i7 = int_is_zero(i2b)
        guard_false(i7) []
        i8 = int_gt(i2c, -7)
        guard_true(i8) []
        i9 = int_is_zero(i2c)
        jump(i1, i2a, i2b, i2c)
        """
        expected = """
        [i1, i2a, i2b, i2c]
        i3 = int_is_zero(i1)
        i4 = int_lt(7, i2a)
        guard_true(i4) []
        i6 = int_le(i2b, -7)
        guard_true(i6) []
        i8 = int_lt(-7, i2c)
        guard_true(i8) []
        i9 = int_is_zero(i2c)
        jump(i1, i2a, i2b, i2c)
        """
        self.optimize_loop(ops, expected)

    def test_division_to_rshift(self):
        ops = """
        [i1, i2]
        i3 = call_pure_i(321, i1, i2, descr=int_py_div_descr)
        i4 = call_pure_i(322, 2, i2, descr=int_py_div_descr)
        i6 = call_pure_i(323, 3, i2, descr=int_py_div_descr)
        i8 = call_pure_i(324, 4, i2, descr=int_py_div_descr)
        i9b = call_pure_i(325, i1, -2, descr=int_py_div_descr)
        i9c = call_pure_i(326, i1, -1, descr=int_py_div_descr)
        i10 = call_pure_i(327, i1, 0, descr=int_py_div_descr)
        i11 = call_pure_i(328, i1, 1, descr=int_py_div_descr)
        i5 = call_pure_i(329, i1, 2, descr=int_py_div_descr)
        i9 = call_pure_i(331, i1, 4, descr=int_py_div_descr)
        jump(i5, i9)
        """
        expected = """
        [i1, i2]
        i3 = call_i(321, i1, i2, descr=int_py_div_descr)
        i4 = call_i(322, 2, i2, descr=int_py_div_descr)
        i6 = call_i(323, 3, i2, descr=int_py_div_descr)
        i8 = call_i(324, 4, i2, descr=int_py_div_descr)
        i9b = call_i(325, i1, -2, descr=int_py_div_descr)
        i9c = call_i(326, i1, -1, descr=int_py_div_descr)
        i10 = call_i(327, i1, 0, descr=int_py_div_descr)
        # i11 = i1
        i5 = int_rshift(i1, 1)
        i9 = int_rshift(i1, 2)
        jump(i5, i9)
        """
        self.optimize_loop(ops, expected)

    def test_division_to_mul_high_nonneg(self):
        from rpython.jit.metainterp.optimizeopt.intdiv import magic_numbers
        for divisor in [3, 5, 12]:
            kk, ii = magic_numbers(divisor)
            ops = """
            [i1]
            i3 = int_ge(i1, 0)
            guard_true(i3) []
            i2 = call_pure_i(321, i1, %d, descr=int_py_div_descr)
            jump(i2)
            """ % divisor
            expected = """
            [i1]
            i3 = int_le(0, i1)
            guard_true(i3) []
            i4 = uint_mul_high(i1, %d)
            i2 = uint_rshift(i4, %d)
            jump(i2)
            """ % (intmask(kk), ii)
            self.optimize_loop(ops, expected)

    def test_mul_to_lshift(self):
        ops = """
        [i1, i2]
        i3 = int_mul(i1, 2)
        i4 = int_mul(2, i2)
        i5 = int_mul(i1, 32)
        i6 = int_mul(i1, i2)
        jump(i5, i6)
        """
        expected = """
        [i1, i2]
        i3 = int_lshift(i1, 1)
        i4 = int_lshift(i2, 1)
        i5 = int_lshift(i1, 5)
        i6 = int_mul(i1, i2)
        jump(i5, i6)
        """
        self.optimize_loop(ops, expected)

    def test_lshift_rshift(self):
        ops = """
        [i1, i2, i2b, i1b]
        i3 = int_lshift(i1, i2)
        i4 = int_rshift(i3, i2)
        i5 = int_lshift(i1, 2)
        i6 = int_rshift(i5, 2)
        i6t= int_eq(i6, i1)
        guard_true(i6t) []
        i7 = int_lshift(i1, 100)
        i8 = int_rshift(i7, 100)
        i9 = int_lt(i1b, 100)
        guard_true(i9) []
        i10 = int_gt(i1b, -100)
        guard_true(i10) []
        i13 = int_lshift(i1b, i2)
        i14 = int_rshift(i13, i2)
        i15 = int_lshift(i1b, 2)
        i16 = int_rshift(i15, 2)
        i17 = int_lshift(i1b, 100)
        i18 = int_rshift(i17, 100)
        i19 = int_eq(i1b, i16)
        guard_true(i19) []
        i20 = int_ne(i1b, i16)
        guard_false(i20) []
        jump(i2, i3, i1b, i2b)
        """
        expected = """
        [i1, i2, i2b, i1b]
        i3 = int_lshift(i1, i2)
        i4 = int_rshift(i3, i2)
        i5 = int_lshift(i1, 2)
        i6 = int_rshift(i5, 2)
        i6t= int_eq(i6, i1)
        guard_true(i6t) []
        i7 = int_lshift(i1, 100)
        i9 = int_lt(i1b, 100)
        guard_true(i9) []
        i10 = int_lt(-100, i1b)
        guard_true(i10) []
        i13 = int_lshift(i1b, i2)
        i14 = int_rshift(i13, i2)
        i15 = int_lshift(i1b, 2)
        i17 = int_lshift(i1b, 100)
        jump(i2, i3, i1b, i2b)
        """
        self.optimize_loop(ops, expected)

    def test_int_div_1(self):
        ops = """
        [i0]
        i1 = call_pure_i(321, i0, 1, descr=int_py_div_descr)
        jump(i1)
        """
        expected = """
        [i0]
        jump(i0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i0]
        i2 = int_eq(i0, 0)
        guard_false(i2) []
        i1 = call_pure_i(321, 0, i0, descr=int_py_div_descr)
        jump(i1)
        """
        expected = """
        [i0]
        i2 = int_is_zero(i0)
        guard_false(i2) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

    @pytest.mark.skipif("LONG_BIT != 64")
    def test_division_bound_bug(self):
        ops = """
        [i4]
        i1 = int_ge(i4, -50)
        guard_true(i1) []
        i2 = int_le(i4, -40)
        guard_true(i2) []
        # here, -50 <= i4 <= -40

        i5 = call_pure_i(321, i4, 30, descr=int_py_div_descr)
        # here, we know that that i5 == -2  (Python-style handling of negatives)
        jump(i5)
        """
        expected = """
        [i4]
        i1 = int_le(-50, i4)
        guard_true(i1) []
        i2 = int_le(i4, -40)
        guard_true(i2) []
        # here, -50 <= i4 <= -40
        i3 = int_invert(i4),
        i5 = uint_mul_high(i3, -8608480567731124087),
        jump(-2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_eq(self):
        ops = """
        [i0, i1]
        i2 = int_le(i0, 4)
        guard_true(i2) []
        i3 = int_eq(i0, i1)
        guard_true(i3) []
        i4 = int_lt(i1, 5)
        guard_true(i4) []
        jump()
        """
        expected = """
        [i0, i1]
        i2 = int_le(i0, 4)
        guard_true(i2) []
        i3 = int_eq(i0, i1)
        guard_true(i3) []
        jump()
        """
        self.optimize_loop(ops, expected)

    def test_bound_eq_const(self):
        ops = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_true(i1) []
        jump(10)
        """
        self.optimize_loop(ops, expected)

    def test_bound_eq_const_not(self):
        ops = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_false(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_eq(i0, 7)
        guard_false(i1) []
        i2 = int_add(i0, 3)
        jump(i2)

        """
        self.optimize_loop(ops, expected)

    def test_bound_ne_const_not(self):
        ops = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_ne(i0, 7)
        guard_true(i1) []
        i2 = int_add(i0, 3)
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_bound_ltne(self):
        ops = """
        [i0, i1]
        i2 = int_lt(i0, 7)
        guard_true(i2) []
        i3 = int_ne(i0, 10)
        guard_true(i2) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_lt(i0, 7)
        guard_true(i2) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_mul_ovf(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_lt(i1, 5)
        guard_true(i3) []
        i4 = int_gt(i1, -10)
        guard_true(i4) []
        i5 = int_mul_ovf(i2, i1)
        guard_no_overflow() []
        i6 = int_lt(i5, -2550)
        guard_false(i6) []
        i7 = int_ge(i5, 1276)
        guard_false(i7) []
        i8 = int_gt(i5, 126)
        guard_true(i8) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_lt(i1, 5)
        guard_true(i3) []
        i4 = int_lt(-10, i1)
        guard_true(i4) []
        i5 = int_mul(i2, i1)
        i8 = int_lt(126, i5)
        guard_true(i8) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_mul_ovf_before(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i22 = int_add(i2, 1)
        i3 = int_mul_ovf(i22, i1)
        guard_no_overflow() []
        i4 = int_lt(i3, 10)
        guard_true(i4) []
        i5 = int_gt(i3, 2)
        guard_true(i5) []
        i6 = int_lt(i1, 0)
        guard_false(i6) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i22 = int_add(i2, 1)
        i3 = int_mul_ovf(i22, i1)
        guard_no_overflow() []
        i4 = int_lt(i3, 10)
        guard_true(i4) []
        i5 = int_lt(2, i3)
        guard_true(i5) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_sub_ovf_before(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_sub_ovf(i2, i1)
        guard_no_overflow() []
        i4 = int_le(i3, 10)
        guard_true(i4) []
        i5 = int_ge(i3, 2)
        guard_true(i5) []
        i6 = int_lt(i1, -10)
        guard_false(i6) []
        i7 = int_gt(i1, 253)
        guard_false(i7) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i3 = int_sub_ovf(i2, i1)
        guard_no_overflow() []
        i4 = int_le(i3, 10)
        guard_true(i4) []
        i5 = int_le(2, i3)
        guard_true(i5) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_int_is_true(self):
        ops = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_gt(i1, 0)
        guard_true(i2) []
        i3 = int_is_true(i1)
        guard_true(i3) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_lt(0, i1)
        guard_true(i2) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_true_is_zero(self):
        ops = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_is_true(i1)
        guard_true(i2) []
        i3 = int_is_zero(i1)
        guard_false(i3) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_add(i0, 1)
        i2 = int_is_true(i1)
        guard_true(i2) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_div_bug(self):
        ops = """
[i0, i1, i2, i3]
i53 = int_and(i2, 63)
i54 = int_lshift(1, i53)
i83 = int_ne(i3, i1)
i123 = int_add(42, i83)
i130 = call_pure_i(12, -87905, i54, descr=int_py_div_descr) []
i181 = int_sub(i123, i130)
i316 = int_and(i181, -17)
guard_value(i316, 42) []
finish()
        """
        # run without timeout
        oldtimeout = pytest.config.option.z3timeout
        pytest.config.option.z3timeout = None
        try:
            self.optimize_loop(ops, ops.replace("call_pure_i", "call_i"))
        finally:
            pytest.config.option.z3timeout = oldtimeout

    def test_int_mul_commutative(self):
        ops = """
        [i0, i1]
        i2 = int_mul(i0, i1)
        i3 = int_mul(i1, i0)
        jump(i2, i3)
        """
        expected = """
        [i0, i1]
        i2 = int_mul(i0, i1)
        jump(i2, i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_bitwise_commutative(self):
        for op in "int_and int_or int_xor".split():
            ops = """
            [i0, i1]
            i2 = intop(i0, i1)
            i3 = intop(i1, i0)
            jump(i2, i3)
            """
            expected = """
            [i0, i1]
            i2 = intop(i0, i1)
            jump(i2, i2)
            """
            self.optimize_loop(ops.replace("intop", op), expected.replace("intop", op))

    def test_int_xor_neg_one_is_invert(self):
        ops = """
        [i0]
        i2 = int_xor(i0, -1)
        i3 = int_xor(-1, i2)
        jump(i3)
        """
        expected = """
        [i0]
        i1 = int_invert(i0)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_uint_ge_implies_int_lt(self):
        # this is a common pattern when reading at a fixed index 0 from a
        # resizable list. the uint_ge is checking that 0 is a valid index
        # (neither negative nor >= i0, the length)
        ops = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = uint_ge(0, i0)
        guard_false(i2) []
        i3 = int_ge(i0, 1)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 0)
        guard_false(i1) []
        i2 = int_is_zero(i0)
        guard_false(i2) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_uint_ge_implies_something_about_index(self):
        # this is a common pattern when reading at an index i0 from a list. the
        # uint_ge is checking that i0 is a valid index (neither negative nor >=
        # i1, the length)
        ops = """
        [i0, i1]
        # check that the length is non-negative
        i2 = int_ge(i1, 0)
        guard_true(i2) []
        i3 = uint_ge(i0, i1)
        guard_false(i3) []
        i4 = int_ge(i0, 0) # this is implied by the uint_ge
        guard_true(i4) []
        jump(i0)
        """
        expected = """
        [i0, i1]
        i2 = int_le(0, i1)
        guard_true(i2) []
        i3 = uint_le(i1, i0)
        guard_false(i3) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_force_ge_zero(self):
        ops = """
        [i0]
        i1 = int_le(i0, 100)
        guard_true(i1) []
        i2 = int_force_ge_zero(i0)
        i3 = int_le(i2, 100)
        guard_true(i3) []
        i4 = int_force_ge_zero(i2)
        finish(i4)
        """
        expected = """
        [i0]
        i1 = int_le(i0, 100)
        guard_true(i1) []
        i2 = int_force_ge_zero(i0)
        finish(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_force_ge_zero_known_negative(self):
        ops = """
        [i0]
        i1 = int_le(i0, -100)
        guard_true(i1) []
        i2 = int_force_ge_zero(i0)
        finish(i2)
        """
        expected = """
        [i0]
        i1 = int_le(i0, -100)
        guard_true(i1) []
        finish(0)
        """
        self.optimize_loop(ops, expected)

    def test_int_force_ge_zero_bug(self):
        ops = """
        [i0]
        i1 = int_and(i0, 1)
        guard_true(i1) []
        i2 = int_force_ge_zero(i0)
        i3 = int_gt(i2, 0) # not true!
        guard_true(i3) []
        finish(i2)
        """
        expected = """
        [i0]
        i1 = int_and(i0, 1)
        guard_true(i1) []
        i2 = int_force_ge_zero(i0)
        i3 = int_lt(0, i2) # not true!
        guard_true(i3) []
        finish(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_eq_1_bool(self):
        ops = """
        [i0]
        i1 = int_and(i0, 1)
        i2 = int_eq(i1, 1)
        finish(i2)
        """
        expected = """
        [i0]
        i1 = int_and(i0, 1)
        finish(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_mul_with_lshift_1(self):
        ops = """
        [i0, i1]
        i2 = int_ge(i1, 0)
        guard_true(i2) []
        i3 = int_le(i1, %s)
        guard_true(i3) []
        i4 = int_lshift(1, i1)
        i5 = int_mul(i0, i4)
        finish(i5)
        """ % (LONG_BIT - 1, )
        expected = """
        [i0, i1]
        i2 = int_le(0, i1)
        guard_true(i2) []
        i3 = int_le(i1, %s)
        guard_true(i3) []
        i4 = int_lshift(1, i1) # dead
        i5 = int_lshift(i0, i1)
        finish(i5)
        """ % (LONG_BIT - 1, )
        self.optimize_loop(ops, expected)

    def test_int_mul_neg_1(self):
        ops = """
        [i0]
        i4 = int_ge(i0, -100000)
        guard_true(i4) []
        i2 = int_mul_ovf(i0, -1)
        guard_no_overflow() []
        i3 = int_add_ovf(i2, 50)
        guard_no_overflow() []
        jump(i3)
        """
        expected = """
        [i0]
        i4 = int_le(-100000, i0)
        guard_true(i4) []
        i2 = int_neg(i0)
        i3 = int_add(i2, 50)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_div_neg_1(self):
        ops = """
        [i0]
        i4 = int_ge(i0, -100000)
        guard_true(i4) []
        i2 = call_pure_i(321, i0, -1, descr=int_py_div_descr)
        i3 = int_add_ovf(i2, 50)
        guard_no_overflow() []
        jump(i3)
        """
        expected = """
        [i0]
        i4 = int_le(-100000, i0)
        guard_true(i4) []
        i2 = int_neg(i0)
        i3 = int_add(i2, 50)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_ovf_backwards(self):
        ops = """
        [i0]
        i1 = int_add_ovf(i0, 1)
        guard_no_overflow() []
        i2 = int_lt(i0, ConstInt(MAXINT))
        guard_true(i2) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_add_ovf(i0, 1)
        guard_no_overflow() []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_ovf_backwards2(self):
        ops = """
        [i0]
        i1 = int_invert(i0)
        i2 = int_add_ovf(i1, 100)
        guard_no_overflow() []
        i3 = int_ge(i0, ConstInt(MININT))
        guard_true(i3) []
        jump(i2)
        """
        expected = """
        [i0]
        i1 = int_invert(i0)
        i2 = int_add_ovf(i1, 100)
        guard_no_overflow() []
        jump(i2)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_ovf_backwards(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(i0, 1)
        guard_no_overflow() []
        i2 = int_gt(i0, ConstInt(MININT))
        guard_true(i2) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_sub_ovf(i0, 1)
        guard_no_overflow() []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_ovf_backwards2(self):
        ops = """
        [i0]
        i1 = int_sub_ovf(1, i0)
        guard_no_overflow() []
        i2 = int_add(ConstInt(MININT), 1)
        i3 = int_gt(i0, i2)
        guard_true(i3) []
        jump(i1)
        """
        expected = """
        [i0]
        i1 = int_sub_ovf(1, i0)
        guard_no_overflow() []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_remove_int_add_ovf_that_always_raises(self):
        ops = """
        [i0]
        i1 = int_ge(i0, ConstInt(MAXINT))
        guard_true(i1) []
        i2 = int_add_ovf(i0, 1)
        guard_overflow() []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_le(ConstInt(MAXINT), i0)
        guard_true(i1) []
        jump(ConstInt(MAXINT))
        """
        self.optimize_loop(ops, expected)

    def test_int_eq_zero_to_int_is_zero(self):
        ops = """
        [i0, i1]
        i2 = int_eq(i0, 0)
        guard_true(i2) []
        i3 = int_eq(0, i1)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0, i1]
        i2 = int_is_zero(i0)
        guard_true(i2) []
        i3 = int_is_zero(i1)
        guard_true(i3) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_int_ne_zero_to_int_is_true(self):
        ops = """
        [i0, i1]
        i2 = int_ne(i0, 0)
        guard_true(i2) []
        i3 = int_ne(0, i1)
        guard_true(i3) []
        jump(i0)
        """
        expected = """
        [i0, i1]
        i2 = int_is_true(i0)
        guard_true(i2) []
        i3 = int_is_true(i1)
        guard_true(i3) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_py_div_bounds_const(self):
        ops = """
        [i0, i1]
        i4 = int_ge(i0, 3)
        guard_true(i4) []
        i5 = int_ge(35, i0)
        guard_true(i5) []
        i2 = call_pure_i(321, i0, 9, descr=int_py_div_descr)
        i3 = int_mul(i2, 9)
        i6 = int_ge(i3, 0)
        guard_true(i6) []
        i7 = int_le(i3, 27)
        guard_true(i7) []
        jump(i3)
        """
        expected = """
        [i0, i1]
        i4 = int_le(3, i0)
        guard_true(i4) []
        i5 = int_le(i0, 35)
        guard_true(i5) []
        i6 = uint_mul_high(i0, -2049638230412172401)
        i7 = uint_rshift(i6, 3)
        i3 = int_mul(i7, 9)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_intmod_bounds_const(self):
        ops = """
        [i0, i1]
        i4 = int_ge(i0, 3)
        guard_true(i4) []
        i2 = call_pure_i(321, i0, 9, descr=int_py_mod_descr)
        i6 = int_ge(i2, 0)
        guard_true(i6) []
        i7 = int_le(i2, 8)
        guard_true(i7) []
        jump(i2)
        """
        expected = """
        [i0, i1]
        i4 = int_le(3, i0)
        guard_true(i4) []
        i6 = uint_mul_high(i0, -2049638230412172401)
        i7 = uint_rshift(i6, 3)
        i3 = int_mul(i7, 9)
        i8 = int_sub(i0, i3)
        jump(i8)
        """
        self.optimize_loop(ops, expected)

    def test_uint_mul_high_bounds(self):
        ops = """
        [i0, i1, i10]
        i2 = int_ge(i0, 0)
        guard_true(i2) []
        i3 = int_ge(i1, 0)
        guard_true(i3) []
        i5 = uint_mul_high(i0, i1)
        i6 = int_ge(i5, 0)
        guard_true(i6) []
        i7 = uint_mul_high(i10, 1)
        jump(i5, i1, i7)
        """
        expected = """
        [i0, i1, i10]
        i2 = int_le(0, i0)
        guard_true(i2) []
        i3 = int_le(0, i1)
        guard_true(i3) []
        i5 = uint_mul_high(i0, i1)
        i7 = uint_mul_high(i10, 1)
        jump(i5, i1, 0)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_ovf_not_removed_but_result_and_args_are_known(self):
        ops = """
        [i1]
        i2 = int_and(i1, -7)
        guard_value(i2, -7) []
        i10 = int_sub_ovf(i1, ConstInt(MAXINT)) # result must be MININT
        guard_no_overflow()[]
        i11 = int_neg(i1) # i1 must be -1 here, and i11 is 1
        i12 = int_mul(i11, i10) # const-folded to MININT
        finish(i12)
        """
        expected = """
        [i1]
        i2 = int_and(i1, -7)
        guard_value(i2, -7) []
        i10 = int_sub_ovf(i1, ConstInt(MAXINT)) # result must be MININT
        guard_no_overflow()[]
        finish(ConstInt(MININT))
        """
        self.optimize_loop(ops, expected)

    def test_record_exact_value(self):
        ops = """
        [i0]
        i1 = int_lt(i0, 4)
        record_exact_value_i(i1, 1) []
        i2 = int_lt(i0, 5)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_lt(i0, 4)
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_and_1(self):
        ops = """
        [i0]
        i1 = int_and(i0, 1)
        i2 = int_eq(i1, 1)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_and(i0, 1)
        guard_true(i1) []
        jump(i0)
        """
        self.optimize_loop(ops, expected)

    def test_int_and_1_of_bool(self):
        ops = """
        [i0]
        i1 = int_eq(i0, 1)
        i2 = int_and(i1, 1)
        guard_true(i2) []
        jump(i0)
        """
        expected = """
        [i0]
        i1 = int_eq(i0, 1)
        guard_true(i1) []
        jump(1)
        """
        self.optimize_loop(ops, expected)

    def test_int_xor_with_itself_indirect(self):
        ops = """
        [i1, i2, i11, i12]
        i3 = int_xor(i1, i2)
        i4 = int_xor(i3, i1)
        i13 = int_xor(i12, i11)
        i14 = int_xor(i13, i11)
        jump(i4, i14)
        """
        expected = """
        [i1, i2, i11, i12]
        i3 = int_xor(i1, i2) # removed by backend
        i13 = int_xor(i12, i11) # removed by backend
        jump(i2, i12)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1, i2, i11, i12]
        i3 = int_xor(i1, i2)
        i4 = int_xor(i1, i3)
        i13 = int_xor(i12, i11) # changed order
        i14 = int_xor(i11, i13) # changed order
        jump(i4, i14)
        """
        expected = """
        [i1, i2, i11, i12]
        i3 = int_xor(i1, i2) # removed by backend
        i13 = int_xor(i12, i11) # removed by backend
        jump(i2, i12)
        """
        self.optimize_loop(ops, expected)

    def test_shift_back_and_forth(self):
        ops = """
        [i1]
        i2 = int_rshift(i1, 15)
        i3 = int_lshift(i2, 15)
        jump(i3) # equal
        """
        expected = """
        [i1]
        i2 = int_rshift(i1, 15) # dead, removed by backend
        i3 = int_and(i1, -32768)
        jump(i3) # equal
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = uint_rshift(i1, 15)
        i3 = int_lshift(i2, 15)
        jump(i3) # equal
        """
        expected = """
        [i1]
        i2 = uint_rshift(i1, 15) # dead, removed by backend
        i3 = int_and(i1, -32768)
        jump(i3) # equal
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = int_lshift(i1, 30)
        i3 = uint_rshift(i2, 30)
        jump(i3) # equal
        """
        expected = """
        [i1]
        i2 = int_lshift(i1, 30) # dead, removed by backend
        i3 = int_and(i1, 17179869183)
        jump(i3) # equal
        """
        self.optimize_loop(ops, expected)

    def test_uint_gt_zero_to_int_is_true(self):
        ops = """
        [i1, i4]
        i2 = uint_gt(i1, 0)
        guard_true(i2) []
        i5 = uint_lt(0, i4)
        guard_true(i5) []
        jump(i1)
        """
        expected = """
        [i1, i4]
        i2 = int_is_true(i1)
        guard_true(i2) []
        i5 = int_is_true(i4)
        guard_true(i5) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_uint_ge_one_to_int_is_true(self):
        ops = """
        [i1]
        i2 = uint_ge(i1, 1)
        guard_true(i2) []
        jump(i1)
        """
        expected = """
        [i1]
        i2 = int_is_true(i1)
        guard_true(i2) []
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_uint_ge_zero_to_int_is_zero(self):
        ops = """
        [i1]
        i2 = uint_ge(0, i1)
        guard_true(i2) []
        jump(i1)
        """
        expected = """
        [i1]
        i2 = int_is_zero(i1)
        guard_true(i2) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = uint_le(i1, 0)
        guard_true(i2) []
        jump(i1)
        """
        expected = """
        [i1]
        i2 = int_is_zero(i1)
        guard_true(i2) []
        jump(0)
        """
        self.optimize_loop(ops, expected)

    def test_two_ands_with_constants(self):
        ops = """
        [i1]
        i2 = int_and(i1, 57)
        i3 = int_and(i2, 504)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_and(i1, 57) # dead
        i3 = int_and(i1, 56)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = int_and(57, i1)
        i3 = int_and(i2, 504)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_and(57, i1) # dead
        i3 = int_and(i1, 56)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = int_and(i1, 57)
        i3 = int_and(504, i2)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_and(i1, 57)
        i3 = int_and(i1, 56)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = int_and(57, i1)
        i3 = int_and(504, i2)
        jump(i3)
        """
        expected = """
        [i1]
        i2 = int_and(57, i1) # dead
        i3 = int_and(i1, 56)
        jump(i3)
        """
        self.optimize_loop(ops, expected)

    def test_and_with_itself(self):
        ops = """
        [i1]
        i2 = int_and(i1, i1)
        jump(i2)
        """
        expected = """
        [i1]
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_useless_and(self):
        # constant version
        ops = """
        [i1]
        i2 = int_and(i1, 927) # i2: 0b0...0???00?????
        i3 = int_rshift(i2, 5) # 0b0...0???00
        i4 = int_or(i3, 96) # 96 == 0b1100000, thus i4 looks like this: 0b0...011???00
        i5 = int_and(i4, 253) # 253 ==                                 0b0...011111101
        i6 = int_and(125, i4)
        jump(i6)
        """
        expected = """
        [i1]
        i2 = int_and(i1, 927)
        i3 = int_rshift(i2, 5)
        i4 = int_or(i3, 96)
        jump(i4)
        """
        self.optimize_loop(ops, expected)

        # non-constant version
        ops = """
        [i1, i10]
        i2 = int_and(i1, 927) # i2: 0b0...0???00?????
        i3 = int_rshift(i2, 5) # 0b0...0???00
        i4 = int_or(i3, 96) # 96 == 0b1100000, thus i4 looks like this: 0b0...011???00
        i5 = int_or(i10, 253)
        i6 = int_and(i4, i5) # this and is just i4
        jump(i6)
        """
        expected = """
        [i1, i10]
        i2 = int_and(i1, 927) # i2: 0b0...0???00?????
        i3 = int_rshift(i2, 5) # 0b0...0???00
        i4 = int_or(i3, 96) # 96 == 0b1100000, thus i4 looks like this: 0b0...011???00
        i5 = int_or(i10, 253)
        jump(i4)
        """
        self.optimize_loop(ops, expected)

    def test_useless_and_real_examples(self):
        ops = """
        [i34]
        i47 = int_and(i34, 281474974613504)
        i49 = uint_rshift(i47, 21) # lshift and rshift turn into a useless and
        i50 = int_lshift(i49, 21)
        jump(i50, i47) # equal
        """
        expected = """
        [i34]
        i47 = int_and(i34, 281474974613504)
        i49 = uint_rshift(i47, 21) # dead
        jump(i47, i47)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i120]
        i122 = int_lshift(i120, 24)
        i128 = int_and(i122, -16711681)
        jump(i128, i122) # equal
        """
        expected = """
        [i120]
        i122 = int_lshift(i120, 24)
        jump(i122, i122) # equal
        """
        self.optimize_loop(ops, expected)

    def test_xor_is_addition(self):
        ops = """
        [i1]
        i2 = int_and(i1, 31)
        i3 = int_xor(i2, 2048)
        i4 = int_sub(i3, 2048)
        jump(i4, i2) # equal
        """
        expected = """
        [i1]
        i2 = int_and(i1, 31)
        i3 = int_xor(i2, 2048) # dead
        jump(i2, i2) # equal
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1, i2]
        i3 = int_and(i1, 31)
        i4 = int_and(i2, 1984) # 0b11111000000
        i7 = int_xor(i4, i3)
        i8 = int_sub(i7, i4)
        jump(i8, i3) # equal
        """
        expected = """
        [i1, i2]
        i3 = int_and(i1, 31)
        i4 = int_and(i2, 1984)
        i7 = int_xor(i4, i3) # dead
        jump(i3, i3) # equal
        """
        self.optimize_loop(ops, expected)

        # check that it gets added to the pure results
        ops = """
        [i1]
        i2 = int_and(i1, 31)
        i3 = int_xor(i2, 2048)
        i4 = int_add(i2, 2048)
        i5 = int_or(i2, 2048)
        jump(i5, i4, i3) # equal
        """
        expected = """
        [i1]
        i2 = int_and(i1, 31)
        i3 = int_xor(i2, 2048)
        jump(i3, i3, i3)
        """
        self.optimize_loop(ops, expected)

    def test_or_xor_add_are_the_same(self):
        ops = """
        [i1]
        i2 = int_and(i1, 1)
        i3 = int_or(i2, 2)
        i4 = int_add(i2, 2)
        i5 = int_xor(i2, 2)
        jump(i5, i4, i3) # equal
        """
        expected = """
        [i1]
        i2 = int_and(i1, 1)
        i3 = int_or(i2, 2)
        jump(i3, i3, i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_or_int_is_false(self):
        ops = """
        [i1, i2]
        i3 = int_or(i1, i2)
        i4 = int_is_true(i3)
        guard_false(i4) []
        jump(i1, i2)
        """
        expected = """
        [i1, i2]
        i3 = int_or(i1, i2)
        i4 = int_is_true(i3)
        guard_false(i4) []
        jump(0, 0)
        """
        self.optimize_loop(ops, expected)

    def test_int_and_int_eq_min_1(self):
        ops = """
        [i1, i2]
        i3 = int_and(i1, i2)
        i4 = int_eq(i3, -1)
        guard_true(i4) []
        jump(i1, i2)
        """
        expected = """
        [i1, i2]
        i3 = int_and(i1, i2)
        i4 = int_eq(i3, -1)
        guard_true(i4) []
        jump(-1, -1)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_int_eq_min_1(self):
        ops = """
        [i1, i2]
        i3 = int_eq(i1, -1)
        i4 = int_sub(i1, i3)
        i5 = int_eq(i4, -1)
        guard_false(i5) []
        jump(i4)
        """
        expected = """
        [i1, i2]
        i3 = int_eq(i1, -1)
        i4 = int_sub(i1, i3)
        jump(i4)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_int_add_consts(self):
        ops = """
        [i1]
        i2 = int_sub(i1, 3)
        i3 = int_add(i2, 6)
        i4 = int_add(i1, 3)
        jump(i3, i4) # equal
        """
        expected = """
        [i1]
        i2 = int_sub(i1, 3) # dead
        i4 = int_add(i1, 3)
        jump(i4, i4)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i2 = int_sub(3, i1)
        i3 = int_add(i2, 6)
        i4 = int_sub(9, i1)
        jump(i3, i4) # equal
        """
        expected = """
        [i1]
        i2 = int_sub(3, i1) # dead
        i4 = int_sub(9, i1)
        jump(i4, i4)
        """
        self.optimize_loop(ops, expected)

    def test_int_sub_int_sub_consts(self):
        ops = """
        [i1]
        i3 = int_sub(i1, 2)
        i4 = int_sub(i3, 1)
        jump(i4) # equal
        """
        expected = """
        [i1]
        i3 = int_sub(i1, 2) # dead
        i4 = int_sub(i1, 3)
        jump(i4)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1]
        i3 = int_sub(2, i1)
        i4 = int_sub(i3, 1)
        jump(i4) # equal
        """
        expected = """
        [i1]
        i3 = int_sub(2, i1) # dead
        i4 = int_sub(1, i1)
        jump(i4)
        """
        self.optimize_loop(ops, expected)

    def test_int_add_int_sub_consts(self):
        ops = """
        [i1]
        i2 = int_add(i1, 1)
        i3 = int_add(i1, 2)
        i4 = int_sub(i3, 1)
        jump(i4, i2) # equal
        """
        expected = """
        [i1]
        i2 = int_add(i1, 1)
        i3 = int_add(i1, 2) # dead
        jump(i2, i2)
        """
        self.optimize_loop(ops, expected)


    def test_int_mul_ovf_fold_overflow_case(self):

        ops = """
        [i0]
        record_exact_value_i(i0, ConstInt(MAXINT))
        i23 = int_mul_ovf(i0, 21)
        guard_overflow() []
        jump(i0)
        """
        expected = """
        [i0]
        jump(ConstInt(MAXINT))
        """
        self.optimize_loop(ops, expected)

    def test_int_mul_ovf_crash(self):
        ops = """
        [i0, i1, i2, i4]
        i12 = int_mul_ovf(i1, i2)
        guard_no_overflow() []
        i5 = int_gt(i0, 2)
        guard_true(i5) []
        i23 = int_mul_ovf(i0, ConstInt(MAXINT))
        guard_overflow() []
        i24 = int_mul_ovf(i1, i2)
        guard_no_overflow() []
        jump(i12, i24)
        """
        expected = """
        [i0, i1, i2, i4]
        i12 = int_mul_ovf(i1, i2)
        guard_no_overflow() []
        i5 = int_lt(2, i0)
        guard_true(i5) []
        jump(i12, i12)
        """
        self.optimize_loop(ops, expected)

    def test_uint_rshift_adds_unknowns(self):
        ops = """
        [i1]
        i3 = uint_rshift(63, i1)
        i4 = int_and(i3, 63)
        jump(i4, i3)
        """
        expected = """
        [i1]
        i3 = uint_rshift(63, i1)
        jump(i3, i3)
        """
        self.optimize_loop(ops, expected)

    def test_int_lt_implies_not_int_eq(self):
        for op in ['int_lt', 'int_gt', 'uint_lt', 'uint_gt']:
            for order in ['i1, i2', 'i2, i1']:
                for eqcmp, guard in [('int_eq', 'guard_false'), ('int_ne', 'guard_true')]:
                    ops = """
                    [i1, i2]
                    i3 = %s(%s)
                    guard_true(i3) []
                    i4 = %s(i1, i2)
                    %s(i4) []
                    jump(i1, i2)
                    """ % (op, order, eqcmp, guard)
                    if op == "int_gt":
                        op = "int_lt"
                        order = ", ".join(order.split(", ")[::-1])
                    if op == "uint_gt":
                        op = "uint_lt"
                        order = ", ".join(order.split(", ")[::-1])
                    expected = """
                    [i1, i2]
                    i3 = %s(%s)
                    guard_true(i3) []
                    jump(i1, i2)
                    """ % (op, order)
                    self.optimize_loop(ops, expected)

    def test_int_eq_implies_not_int_lt(self):
        for op in ['int_lt', 'int_gt', 'uint_lt', 'uint_gt']:
            for order in ['i1, i2', 'i2, i1']:
                for eqcmp, guard in [('int_eq', 'guard_true'), ('int_ne', 'guard_false')]:
                    ops = """
                    [i1, i2]
                    i3 = %s(%s)
                    %s(i3) []
                    i4 = %s(i1, i2)
                    guard_false(i4) []
                    jump(i1, i2)
                    """ % (eqcmp, order, guard, op)
                    expected = """
                    [i1, i2]
                    i3 = %s(%s)
                    %s(i3) []
                    jump(i1, i2)
                    """ % (eqcmp, order, guard)
                    self.optimize_loop(ops, expected)

    def test_int_eq_implies_int_ge(self):
        for op in ['int_le', 'int_ge', 'uint_le', 'uint_ge']:
            for order in ['i1, i2', 'i2, i1']:
                for eqcmp, guard in [('int_eq', 'guard_true'), ('int_ne', 'guard_false')]:
                    ops = """
                    [i1, i2]
                    i3 = %s(%s)
                    %s(i3) []
                    i4 = %s(i1, i2)
                    guard_true(i4) []
                    jump(i1, i2)
                    """ % (eqcmp, order, guard, op)
                    expected = """
                    [i1, i2]
                    i3 = %s(%s)
                    %s(i3) []
                    jump(i1, i2)
                    """ % (eqcmp, order, guard)
                    self.optimize_loop(ops, expected)

    def test_int_eq_x_int_add_x_const(self):
        ops = """
        [i1]
        i3 = int_add(63, i1)
        i4 = int_eq(i3, i1)
        guard_false(i4) []
        jump(i1)
        """
        expected = """
        [i1]
        i3 = int_add(63, i1)
        jump(i1)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [i1, i2]
        i9 = int_gt(i2, 0)
        guard_true(i9) []
        i3 = int_sub(i1, i2)
        i4 = int_eq(i3, i1)
        guard_false(i4) []
        jump(i1)
        """
        expected = """
        [i1, i2]
        i9 = int_lt(0, i2)
        guard_true(i9) []
        i3 = int_sub(i1, i2)
        jump(i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_is_zero_int_sub(self):
        ops = """
        [i1, i2]
        i3 = int_eq(i1, i2)
        i4 = int_sub(i2, i1)
        i5 = int_is_zero(i4)
        jump(i5, i3) # equal
        """
        expected = """
        [i1, i2]
        i3 = int_eq(i1, i2)
        i4 = int_sub(i2, i1) # dead
        jump(i3, i3) # equal
        """
        self.optimize_loop(ops, expected)

    def test_int_neg_int_neg(self):
        ops = """
        [i1]
        i2 = int_neg(i1)
        i3 = int_neg(i2)
        jump(i1, i2, i3) # equal
        """
        expected = """
        [i1]
        i2 = int_neg(i1)
        jump(i1, i2, i1)
        """
        self.optimize_loop(ops, expected)

    def test_int_shift_0(self):
        ops = """
        [i1]
        i2 = int_lshift(i1, 0)
        i3 = int_lshift(0, i1)
        i4 = int_rshift(i1, 0)
        i5 = int_rshift(0, i1)
        i6 = uint_rshift(i1, 0)
        i7 = uint_rshift(0, i1)
        jump(i2, i3, i4, i5, i6, i7) # equal
        """
        expected = """
        [i1]
        jump(i1, 0, i1, 0, i1, 0) # equal
        """
        self.optimize_loop(ops, expected)

    def test_guard_int_is_zero(self):
        ops = """
        [i1]
        i2 = int_eq(i1, 35)
        i4 = int_is_zero(i2)
        guard_true(i4) []
        jump(i1) # equal
        """
        expected = """
        [i1]
        i2 = int_eq(i1, 35)
        i4 = int_is_zero(i2) # dead
        guard_false(i2) []
        jump(i1) # equal
        """
        self.optimize_loop(ops, expected)

    @pytest.mark.xfail()
    def test_int_ge_int_add_no_ovf(self):
        ops = """
        [i0, i5]
        i7 = int_ge(i0, i5)
        guard_false(i7) []
        i9 = int_add(i0, 1)
        i17 = int_ge(i9, i0)
        jump(i17, 1) # constant
        """
        expected = """
        [i0, i5]
        i7 = int_ge(i0, i5)
        guard_false(i7) []
        i9 = int_add(i0, 1)
        jump(1, 1) # constant
        """
        self.optimize_loop(ops, expected)

    def test_int_le_to_int_is_true(self):
        ops = """
        [i1]
        i2 = int_le(0, i1)
        guard_true(i2) []
        i3 = int_le(i1, 0)
        i4 = int_is_zero(i1)
        jump(i3, i4) # equal
        """
        expected = """
        [i1]
        i2 = int_le(0, i1)
        guard_true(i2) []
        i3 = int_is_zero(i1)
        jump(i3, i3) # equal
        """
        self.optimize_loop(ops, expected)


    # ____________________________________________________________
    # exhaustive ordering tests

    @staticmethod
    def _make_test_cmp_function(opfunc, flip, negate, name):
        def cmp(a, b):
            if flip:
                a, b = b, a
            res = opfunc(a, b)
            if negate:
                res = not res
            return res
        if negate:
            name = "not_" + name
        if flip:
            name += "_b_a"
        else:
            name += "_a_b"
        cmp.func_name = name
        return cmp

    @staticmethod
    def _check_cmp_implies(cmp1, cmp2, unsigned):
        if unsigned:
            r = range(0, 8)
        else:
            r = range(-4, 4)
        for a in r:
            for b in r:
                if cmp1(a, b) and not cmp2(a, b):
                    return False
        return True

    @staticmethod
    def _check_cmp_invalid(cmp1, cmp2, unsigned):
        if unsigned:
            r = range(0, 8)
        else:
            r = range(-4, 4)
        for a in r:
            for b in r:
                if cmp1(a, b) and cmp2(a, b):
                    return False
        return True


    ORDERING_OPS = [
        ('int_lt', operator.lt),
        ('int_gt', operator.gt),
        ('int_le', operator.le),
        ('int_ge', operator.ge),
        ('int_eq', operator.eq),
        ('int_ne', operator.ne),
    ]

    @pytest.mark.parametrize('op1,opfunc1', ORDERING_OPS)
    @pytest.mark.parametrize('op2,opfunc2', ORDERING_OPS)
    @pytest.mark.parametrize('flip2', [False, True])
    @pytest.mark.parametrize('negate1', [False, True])
    @pytest.mark.parametrize('negate2', [False, True])
    @pytest.mark.parametrize('unsigned', [False, True])
    def test_order_implications_all_compinations(self, op1, opfunc1, op2, opfunc2, flip2, negate1, negate2, unsigned):
        def negate_to_guardkind(negate):
            return 'false' if negate else 'true'
        def flip_args(flip):
            return 'i0, i1' if not flip else 'i1, i0'
        def normalize_op(op, flip=False):
            if "int_gt" in op:
                flip = not flip
                op = "u" * unsigned + "int_lt"
            if "int_ge" in op:
                flip = not flip
                op = "u" * unsigned + "int_le"
            return "%s(%s)" % (op, flip_args(flip))

        if unsigned and op1 in ("int_lt", "int_gt", "int_le", "int_ge"):
            op1 = "u" + op1
        if unsigned and op2 in ("int_lt", "int_gt", "int_le", "int_ge"):
            op2 = "u" + op2

        cmp1 = self._make_test_cmp_function(opfunc1, False, negate1, op1)
        cmp2 = self._make_test_cmp_function(opfunc2, flip2, negate2, op2)
        ops = """
        [i0, i1]
        i2 = %s(i0, i1)
        guard_%s(i2) []
        i3 = %s(%s)
        guard_%s(i3) []
        jump(i0, i1)
        """ % (op1, negate_to_guardkind(negate1),
               op2, flip_args(flip2),
               negate_to_guardkind(negate2))
        print("_" * 60)
        print(op1, op2, flip2, negate1, negate2, unsigned)
        print(ops)
        # if the sequence of guards is not logically consistent we might or
        # might not recognize this, either is fine. but we shouldn't opimize
        # anything
        invalid_is_fine = self._check_cmp_invalid(cmp1, cmp2, unsigned)
        implies = self._check_cmp_implies(cmp1, cmp2, unsigned)
        if implies:
            expected = """
            [i0, i1]
            i2 = %s
            guard_%s(i2) []
            jump(i0, i1)
            """ % (normalize_op(op1), negate_to_guardkind(negate1))
        elif self._check_cmp_implies(cmp1, lambda a, b: cmp2(a, b) == (a == b), unsigned):
            # there's not implication, but we can rewrite the second guard to a
            # cmp, which is more precise
            flip2adjust = "_g" in op2
            expected = """
            [i0, i1]
            i2 = %s
            guard_%s(i2) []
            i3 = int_eq(%s)
            guard_%s(i3) []
            jump(i0, i1)
            """ % (normalize_op(op1), negate_to_guardkind(negate1),
                   flip_args(flip2 ^ flip2adjust), negate_to_guardkind(negate2))
        else:
            expected = """
            [i0, i1]
            i2 = %s
            guard_%s(i2) []
            i3 = %s
            guard_%s(i3) []
            jump(i0, i1)
            """ % (normalize_op(op1), negate_to_guardkind(negate1),
                   normalize_op(op2, flip2), negate_to_guardkind(negate2))

        print(expected)
        try:
            self.optimize_loop(ops, expected)
        except InvalidLoop:
            if not invalid_is_fine:
                raise

        if not implies or not self._check_cmp_implies(cmp2, cmp1, unsigned):
            return
        # they are equivalent!
        print("_" * 60)
        print("equivalent!")
        ops = """
        [i0, i1]
        i2 = %s(i0, i1)
        i3 = %s(%s)
        jump(i2, i3)
        """ % (op1, op2, flip_args(flip2))
        if negate1 == negate2:
            expected = """
            [i0, i1]
            i2 = %s
            jump(i2, i2)
            """ % (normalize_op(op1), )
        else:
            expected = """
            [i0, i1]
            i2 = %s
            i3 = int_is_zero(i2)
            jump(i2, i3)
            """ % (normalize_op(op1), )
        print(ops)
        print(expected)
        self.optimize_loop(ops, expected)


class TestComplexIntOpts(BaseTestBasic):

    def test_mul_ovf_before(self):
        ops = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i22 = int_add(i2, 1)
        i3 = int_mul_ovf(i22, i1)
        guard_no_overflow() []
        i4 = int_lt(i3, 10)
        guard_true(i4) []
        i5 = int_gt(i3, 2)
        guard_true(i5) []
        i6 = int_lt(i1, 0)
        guard_false(i6) []
        jump(i0, i1)
        """
        expected = """
        [i0, i1]
        i2 = int_and(i0, 255)
        i22 = int_add(i2, 1)
        i3 = int_mul_ovf(i22, i1)
        guard_no_overflow() []
        i4 = int_lt(i3, 10)
        guard_true(i4) []
        i5 = int_lt(2, i3)
        guard_true(i5) []
        jump(i0, i1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_arraylen(self):
        ops = """
        [i0, p0]
        p1 = new_array(i0, descr=arraydescr)
        i1 = arraylen_gc(p1, descr=arraydescr)
        i2 = int_gt(i1, -1)
        guard_true(i2) []
        setarrayitem_gc(p0, 0, p1, descr=arraydescr)
        jump(i0, p0)
        """
        expected = """
        [i0, p0]
        p1 = new_array(i0, descr=arraydescr)
        setarrayitem_gc(p0, 0, p1, descr=arraydescr)
        jump(i0, p0)
        """
        self.optimize_loop(ops, expected)
        ops = """
        [p0, p1]
        i1 = arraylen_gc(p1, descr=arraydescr)
        i2 = int_gt(i1, -1)
        guard_true(i2) []
        setarrayitem_gc(p1, 0, p0, descr=arraydescr)
        jump(p0, p1)
        """
        expected = """
        [p0, p1]
        i1 = arraylen_gc(p1, descr=arraydescr)
        setarrayitem_gc(p1, 0, p0, descr=arraydescr)
        jump(p0, p1)
        """
        self.optimize_loop(ops, expected)

    def test_bound_strlen(self):
        ops = """
        [p0]
        i0 = strlen(p0)
        i1 = int_ge(i0, 0)
        guard_true(i1) []
        jump(p0)
        """
        # The dead strlen will be eliminated be the backend.
        expected = """
        [p0]
        i0 = strlen(p0)
        jump(p0)
        """
        self.optimize_loop(ops, expected)

        ops = """
        [p0]
        i0 = unicodelen(p0)
        i1 = int_ge(i0, 0)
        guard_true(i1) []
        jump(p0)
        """
        # The dead unicodelen will be eliminated be the backend.
        expected = """
        [p0]
        i0 = unicodelen(p0)
        jump(p0)
        """
        self.optimize_loop(ops, expected)

    def test_bound_unsigned_lt(self):
        ops = """
        [i0]
        i2 = int_lt(i0, 10)
        guard_true(i2) []
        i3 = int_ge(i0, 0)
        guard_true(i3) []
        i4 = uint_lt(i0, 16)
        guard_true(i4) []
        jump()
        """
        expected = """
        [i0]
        i2 = int_lt(i0, 10)
        guard_true(i2) []
        i3 = int_le(0, i0)
        guard_true(i3) []
        jump()
        """
        self.optimize_loop(ops, expected)

    @pytest.mark.skipif("LONG_BIT != 64")
    def test_lshift_backwards_bug(self):
        ops = """
        [i1]
        i2 = uint_le(27, i1)
        i3 = int_lshift(i2, 54)
        guard_value(i3, 18014398509481984) []
        jump()
        """
        self.optimize_loop(ops, ops) # used to crash

    def test_mul_backwards_bug(self):
        ops = """
        [i1]
        i0 = int_and(i1, 59)
        guard_value(i0, 40) []
        i2 = int_mul_ovf(-25, i1)
        guard_no_overflow() []
        i3 = int_and(i2, 8)
        guard_value(i3, 8) []
        jump()
        """
        self.optimize_loop(ops, ops) # used to crash

