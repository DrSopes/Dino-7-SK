import cocotb
from cocotb.triggers import RisingEdge, Timer

from test import (
    SEG_DP,
    S_IDLE,
    S_RUN,
    S_JUMP,
    S_HIT,
    S_SCORE,
    apply_reset,
    gl_skip_lite,
    has_bit,
    is_gatelevel,
    max_score,
    obs_c,
    obs_f,
    obs_g,
    score,
    seg7_encode,
    start_clock,
    state,
    uo,
)


def dut_i(dut):
    return dut.user_project


async def settle():
    await Timer(1, unit="ns")


async def step_clk(dut, cycles=1):
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await settle()


@cocotb.test()
async def test_seg7_idle_exhaustive(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_seg7_idle_exhaustive", "requires RTL-visible internal regs")
        return

    for val in range(10):
        dut_i(dut).state.value = S_IDLE
        dut_i(dut).max_score.value = val
        dut_i(dut).score.value = 0
        dut_i(dut).blink_timer.value = 0
        await settle()
        expected = 0x80 | seg7_encode(val)
        assert uo(dut) == expected, (
            f"[FAIL] IDLE seg7 mismatch for {val}: expected 0x{expected:02X}, got 0x{uo(dut):02X}"
        )

    dut._log.info("[PASS] Exhaustive IDLE seg7 test passed")


@cocotb.test()
async def test_seg7_score_exhaustive(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_seg7_score_exhaustive", "requires RTL-visible internal regs")
        return

    for val in range(10):
        dut_i(dut).state.value = S_SCORE
        dut_i(dut).score.value = val
        dut_i(dut).max_score.value = 9 - val
        dut_i(dut).blink_timer.value = 0
        await settle()

        expected_score = seg7_encode(val)
        assert uo(dut) == expected_score, (
            f"[FAIL] SCORE current-score mismatch for {val}: expected 0x{expected_score:02X}, got 0x{uo(dut):02X}"
        )
        assert not has_bit(uo(dut), SEG_DP), f"[FAIL] DP should be low for visible score {val}"

        dut_i(dut).blink_timer.value = 8
        dut_i(dut).max_score.value = val
        await settle()

        expected_high = 0x80 | seg7_encode(val)
        assert uo(dut) == expected_high, (
            f"[FAIL] SCORE high-score mismatch for {val}: expected 0x{expected_high:02X}, got 0x{uo(dut):02X}"
        )
        assert has_bit(uo(dut), SEG_DP), f"[FAIL] DP should be high for high-score display {val}"

    dut._log.info("[PASS] Exhaustive SCORE seg7/blink test passed")


@cocotb.test()
async def test_gameplay_output_mapping(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_gameplay_output_mapping", "requires RTL-visible internal regs")
        return

    dut_i(dut).state.value = S_RUN
    dut_i(dut).obs_c.value = 1
    dut_i(dut).obs_g.value = 0
    dut_i(dut).obs_f.value = 1
    dut_i(dut).obs_passed.value = 1
    dut_i(dut).cooldown_timer.value = 2
    await settle()

    expected_run = 0b11001101
    assert uo(dut) == expected_run, (
        f"[FAIL] RUN mapping mismatch: expected 0x{expected_run:02X}, got 0x{uo(dut):02X}"
    )

    dut_i(dut).state.value = S_JUMP
    dut_i(dut).obs_c.value = 0
    dut_i(dut).obs_g.value = 1
    dut_i(dut).obs_f.value = 0
    dut_i(dut).obs_passed.value = 1
    dut_i(dut).cooldown_timer.value = 0
    await settle()

    expected_jump = 0b00011010
    assert uo(dut) == expected_jump, (
        f"[FAIL] JUMP mapping mismatch: expected 0x{expected_jump:02X}, got 0x{uo(dut):02X}"
    )

    dut._log.info("[PASS] Gameplay output mapping test passed")


@cocotb.test()
async def test_obstacle_pipeline_jump_scores(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_obstacle_pipeline_jump_scores", "requires RTL-visible internal regs")
        return

    dut_i(dut).state.value = S_JUMP
    dut_i(dut).jump_timer.value = 7
    dut_i(dut).clk_div.value = 0
    dut_i(dut).frame_max.value = 0
    dut_i(dut).lfsr.value = 0
    dut_i(dut).score.value = 0
    dut_i(dut).max_score.value = 0
    dut_i(dut).obs_c.value = 1
    dut_i(dut).obs_g.value = 0
    dut_i(dut).obs_f.value = 0
    dut_i(dut).obs_passed.value = 0
    await settle()

    await step_clk(dut, 2)
    assert obs_c(dut) == 0 and obs_g(dut) == 1 and obs_f(dut) == 0, (
        f"[FAIL] stage1 mismatch: c/g/f=({obs_c(dut)}/{obs_g(dut)}/{obs_f(dut)})"
    )

    await step_clk(dut, 1)
    assert obs_c(dut) == 0 and obs_g(dut) == 0 and obs_f(dut) == 1, (
        f"[FAIL] stage2 mismatch: c/g/f=({obs_c(dut)}/{obs_g(dut)}/{obs_f(dut)})"
    )

    await step_clk(dut, 1)
    assert obs_f(dut) == 0 and dut_i(dut).obs_passed.value.integer == 1, (
        f"[FAIL] stage3 mismatch: obs_f={obs_f(dut)} obs_passed={dut_i(dut).obs_passed.value.integer}"
    )

    await step_clk(dut, 1)
    assert score(dut) == 1, f"[FAIL] Score should increment after a jumped obstacle, got {score(dut)}"
    assert state(dut) == S_JUMP, f"[FAIL] State should still be JUMP during short pipeline test, got {state(dut)}"

    dut._log.info("[PASS] Obstacle pipeline / jump-score test passed")


@cocotb.test()
async def test_run_hit_updates_high_score(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_run_hit_updates_high_score", "requires RTL-visible internal regs")
        return

    dut_i(dut).state.value = S_RUN
    dut_i(dut).frame_max.value = 0
    dut_i(dut).clk_div.value = 0
    dut_i(dut).score.value = 3
    dut_i(dut).max_score.value = 1
    dut_i(dut).obs_c.value = 0
    dut_i(dut).obs_g.value = 0
    dut_i(dut).obs_f.value = 1
    dut_i(dut).obs_passed.value = 0
    dut_i(dut).cooldown_timer.value = 0
    dut_i(dut).lfsr.value = 0
    await settle()

    await step_clk(dut, 2)
    assert state(dut) == S_HIT, f"[FAIL] RUN + obs_f should transition to HIT, got {state(dut)}"
    assert max_score(dut) == 3, f"[FAIL] max_score should update on hit, got {max_score(dut)}"
    assert uo(dut) == 0xFF, f"[FAIL] HIT output should be 0xFF, got 0x{uo(dut):02X}"

    dut._log.info("[PASS] RUN hit / high-score update test passed")