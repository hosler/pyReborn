"""Client-runtime integration regression for GS2 parameter binding order."""

import struct

from reborn_protocol.gs2 import GS2Container, FunctionEntry, Op, decode
from pyreborn.gs2_client import ClientGS2


def _op(opnum, value=None):
    if value is None:
        return bytes([opnum])
    return bytes([opnum, 0xF3]) + struct.pack(">b", value)


def _var(index):
    return bytes([Op.OP_TYPE_VAR, 0xF0, index])


def _parameter_branch_fixture():
    # function choose(first, second, third) {
    #   if (first) return 11;
    #   return 22;
    # }
    # Both compilers push parameter references in REVERSE declaration
    # order (pop order == declaration order); see
    # reborn-protocol/tests/test_gs2_parameter_binding_order.py for the
    # oracle citations.
    declarations = b"".join(_op(Op.OP_TEMP) + _var(i)
                            + _op(Op.OP_MEMBER_ACCESS)
                            for i in reversed(range(3)))
    prefix = (_op(Op.OP_TYPE_ARRAY) + declarations
              + _op(Op.OP_FUNC_PARAMS_END) + _op(Op.OP_JMP) + _var(0))
    false_index = len(decode(prefix)) + 3
    code = (prefix + _op(Op.OP_IF, false_index) + _op(Op.OP_TYPE_NUMBER, 11)
            + _op(Op.OP_RET) + _op(Op.OP_TYPE_NUMBER, 22) + _op(Op.OP_RET))
    return GS2Container(functions=[FunctionEntry("choose", 0)],
                        strings=["first", "second", "third"], code=code)


def test_gs2_parameter_binding_order_first_argument_reaches_each_branch():
    runtime = ClientGS2()
    vm = runtime.load_bytecode("weapon", "parameter-order",
                               _parameter_branch_fixture())

    assert vm.call("choose", 1, 0, 0) == 11
    assert vm.call("choose", 0, 1, 1) == 22
