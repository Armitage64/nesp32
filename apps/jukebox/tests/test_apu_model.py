from apu_model import ApuState, equivalent, is_redundant


def test_plain_registers_are_redundant_only_when_known_equal():
    assert is_redundant(0x00, 0x30, {0x00: 0x30})
    assert not is_redundant(0x00, 0x31, {0x00: 0x30})
    assert not is_redundant(0x00, 0x30, {})
    assert is_redundant(0x11, 0x30, {0x11: 0x30})


def test_length_loads_and_frame_counter_are_never_redundant():
    for register in (0x03, 0x07, 0x0B, 0x0F, 0x17):
        assert not is_redundant(register, 0x08, {register: 0x08})


def test_sweep_is_redundant_only_while_disabled():
    assert is_redundant(0x01, 0x08, {0x01: 0x08})
    assert not is_redundant(0x01, 0x88, {0x01: 0x88})


def test_length_load_needs_the_channel_enabled():
    state = ApuState()
    state.run([(0x03, 0x08)])
    assert state.active == 0
    state.run([(0x15, 0x01), (0x03, 0x08)])
    assert state.active == 0x01
    state.run([(0x15, 0x00)])
    assert state.active == 0


def test_triggers_on_different_channels_commute():
    assert equivalent([(0x07, 0x08), (0x03, 0x08)], [(0x03, 0x08), (0x07, 0x08)])


def test_enable_then_load_differs_from_load_then_enable():
    assert not equivalent([(0x15, 0x01), (0x03, 0x08)], [(0x03, 0x08), (0x15, 0x01)])


def test_a_repeated_trigger_is_not_the_same_as_one():
    assert not equivalent([(0x03, 0x08), (0x03, 0x08)], [(0x03, 0x08)])


def test_a_skipped_write_matches_when_the_value_was_known():
    assert equivalent([(0x00, 0x30)], [], known={0x00: 0x30})
    assert not equivalent([(0x00, 0x30)], [])
