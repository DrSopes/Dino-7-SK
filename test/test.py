import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

SEG_A = 1 << 0
SEG_B = 1 << 1
SEG_C = 1 << 2
SEG_D = 1 << 3
SEG_E = 1 << 4
SEG_F = 1 << 5
SEG_G = 1 << 6
SEG_DP = 1 << 7

ALL_ON = 0xFF

S_IDLE = 0
S_RUN = 1
S_JUMP = 2
S_HIT = 3
S_SCORE = 4

GL_EXTENDED = os.getenv("GL_EXTENDED", "0") == "1"
GL_TIMEOUT_SCALE = int(os.getenv("GL_TIMEOUT_SCALE", "20"))

def sig_u(obj, name="signal"):
    v = obj.value
    try:
        return v.to_unsigned() if hasattr(v, "to_unsigned") else int(v)
    except ValueError:
        raise AssertionError(f"[FAIL] {name} contains X/Z: {v!s}")

def dut_i(dut):
    return dut.user_project

def has_internal(dut, name):
    return getattr(dut_i(dut), name, None) is not None

def internal_u(dut, name):
    obj = getattr(dut_i(dut), name, None)
    if obj is None:
        return None
    return sig_u(obj, name)

def is_gatelevel(dut):
    return not has_internal(dut, "state")

def is_gl_extended():
    return GL_EXTENDED

def scaled_timeout(dut, base_cycles):
    if is_gatelevel(dut):
        return base_cycles * GL_TIMEOUT_SCALE
    return base_cycles

def uo(dut):
    return sig_u(dut.uo_out, "uo_out")

def ui(dut):
    return sig_u(dut.ui_in, "ui_in")

def state(dut):
    return internal_u(dut, "state")

def score(dut):
    return internal_u(dut, "score")

def max_score(dut):
    return internal_u(dut, "max_score")

def cooldown(dut):
    return internal_u(dut, "cooldown_timer")

def frame_max(dut):
    return internal_u(dut, "frame_max")

def obs_c(dut):
    return internal_u(dut, "obs_c")

def obs_g(dut):
    return internal_u(dut, "obs_g")

def obs_f(dut):
    return internal_u(dut, "obs_f")

def has_bit(value, bitmask):
    return (value & bitmask) != 0

def seg7_encode(val):
    table = {
        0: 0x3F,
        1: 0x06,
        2: 0x5B,
        3: 0x4F,
        4: 0x66,
        5: 0x6D,
        6: 0x7D,
        7: 0x07,
        8: 0x7F,
        9: 0x6F,
    }
    return table.get(int(val) & 0xF, 0x00)

def expected_idle_output(hs):
    return 0x80 | seg7_encode(hs)

def gl_skip_lite(dut, name, reason):
    dut._log.info(f"[SKIP-LITE] {name}: {reason}")
    return

def log_state(dut, tag="STATE"):
    if is_gatelevel(dut):
        dut._log.info(f"[{tag}] uo_out=0x{uo(dut):02X} (gate-level: internal nets unavailable)")
        return

    dut._log.info(
        f"[{tag}] "
        f"uo_out=0x{uo(dut):02X} "
        f"state={state(dut)} "
        f"score={score(dut)} "
        f"max_score={max_score(dut)} "
        f"cooldown={cooldown(dut)} "
        f"frame_max={frame_max(dut)} "
        f"obs(c/g/f)=({obs_c(dut)}/{obs_g(dut)}/{obs_f(dut)})"
    )

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await ClockCycles(dut.clk, 1)

async def apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111):
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = ((seed_bits & 0xF) << 4) | ((difficulty_bits & 0x3) << 2)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    log_state(dut, "AFTER_RESET")

async def pulse_jump(dut, cycles=2):
    dut.ui_in.value = ui(dut) | 0x01
    await ClockCycles(dut.clk, cycles)
    dut.ui_in.value = ui(dut) & ~0x01

async def pulse_game_reset(dut, cycles=2):
    dut.ui_in.value = ui(dut) | 0x02
    await ClockCycles(dut.clk, cycles)
    dut.ui_in.value = ui(dut) & ~0x02

async def hold_jump_until_output_leaves_idle(dut, timeout_cycles=80):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    dut._log.info("[STEP] Holding jump until output leaves idle")
    start = uo(dut)
    dut.ui_in.value = ui(dut) | 0x01

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if uo(dut) != start:
            dut._log.info(f"[PASS] Left idle output after {i+1} cycles")
            dut.ui_in.value = ui(dut) & ~0x01
            await ClockCycles(dut.clk, 1)
            log_state(dut, "AFTER_START")
            return

    dut.ui_in.value = ui(dut) & ~0x01
    raise AssertionError("[FAIL] Output never left IDLE while jump was held")

async def hold_jump_until_start(dut, timeout_cycles=80):
    if is_gatelevel(dut):
        await hold_jump_until_output_leaves_idle(dut, timeout_cycles)
        return

    dut._log.info("[STEP] Holding jump until game leaves IDLE")
    dut.ui_in.value = ui(dut) | 0x01

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) != S_IDLE:
            dut._log.info(f"[PASS] Left IDLE after {i+1} cycles")
            dut.ui_in.value = ui(dut) & ~0x01
            await ClockCycles(dut.clk, 1)
            log_state(dut, "AFTER_START")
            return

    dut.ui_in.value = ui(dut) & ~0x01
    raise AssertionError("[FAIL] Game never left IDLE")

async def wait_for_output_change(dut, timeout_cycles=120, label="output change"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    start = uo(dut)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        now = uo(dut)
        if now != start:
            dut._log.info(
                f"[PASS] {label} after {i+1} cycles: 0x{start:02X} -> 0x{now:02X}"
            )
            return now
    raise AssertionError(f"[FAIL] No {label} within {timeout_cycles} cycles")

async def wait_for_state(dut, target_state, timeout_cycles=400, label="state"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError(f"[FAIL] wait_for_state({label}) requires RTL-visible internal nets")

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) == target_state:
            dut._log.info(f"[PASS] Reached {label} after {i+1} cycles")
            log_state(dut, f"AT_{label.upper()}")
            return
    raise AssertionError(f"[FAIL] Did not reach {label} within {timeout_cycles} cycles")

async def wait_for_all_on(dut, timeout_cycles=400, label="all-on hit"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if uo(dut) == ALL_ON:
            dut._log.info(f"[PASS] Reached {label} after {i+1} cycles")
            log_state(dut, "AT_HIT")
            return
    raise AssertionError(f"[FAIL] Did not reach {label} within {timeout_cycles} cycles")

async def wait_for_score_screen_visible(dut, timeout_cycles=250):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        val = uo(dut)
        if val != ALL_ON and val != expected_idle_output(0):
            dut._log.info(f"[PASS] Visible score-like screen after {i+1} cycles (0x{val:02X})")
            log_state(dut, "AT_SCORE")
            return
    raise AssertionError("[FAIL] Score screen not observed")

async def wait_for_hit_and_score(dut):
    if is_gatelevel(dut):
        await wait_for_all_on(dut, timeout_cycles=400, label="hit")
        await wait_for_score_screen_visible(dut, timeout_cycles=250)
        return

    await wait_for_state(dut, S_HIT, timeout_cycles=400, label="hit")
    assert uo(dut) == ALL_ON, f"[FAIL] HIT output should be 0xFF, got 0x{uo(dut):02X}"
    await wait_for_state(dut, S_SCORE, timeout_cycles=250, label="score")
    assert uo(dut) != ALL_ON, "[FAIL] SCORE screen should not remain all-on"

async def wait_for_dp_toggle_in_score(dut, timeout_cycles=300):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    seen0 = False
    seen1 = False

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        val = uo(dut)
        if val == ALL_ON:
            continue
        if has_bit(val, SEG_DP):
            seen1 = True
        else:
            seen0 = True
        if seen0 and seen1:
            dut._log.info(f"[PASS] DP toggled after {i+1} cycles")
            return

    raise AssertionError("[FAIL] DP did not toggle")

async def autoplay_until_score_increase(dut, timeout_cycles=1500):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] autoplay_until_score_increase requires RTL-visible score")

    last_score = score(dut)

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)

        if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
            dut.ui_in.value = ui(dut) | 0x01
            await ClockCycles(dut.clk, 1)
            dut.ui_in.value = ui(dut) & ~0x01

        if score(dut) > last_score:
            dut._log.info(f"[PASS] Score increased from {last_score} to {score(dut)} after {i+1} cycles")
            return

    raise AssertionError("[FAIL] Could not increase score with autoplay")

async def autoplay_until_score_at_least(dut, target, timeout_cycles=5000):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] autoplay_until_score_at_least requires RTL-visible score")

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)

        if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
            dut.ui_in.value = ui(dut) | 0x01
            await ClockCycles(dut.clk, 1)
            dut.ui_in.value = ui(dut) & ~0x01

        if score(dut) >= target:
            dut._log.info(f"[PASS] Reached score {score(dut)} after {i+1} cycles")
            return

        if state(dut) == S_SCORE and score(dut) < target:
            raise AssertionError(f"[FAIL] Died before reaching score {target}, final score={score(dut)}")

    raise AssertionError(f"[FAIL] Timeout before reaching score {target}")

async def wait_for_run_ready(dut, timeout_cycles=300):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] wait_for_run_ready requires RTL-visible state/cooldown")

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) == S_RUN and cooldown(dut) == 0:
            dut._log.info(f"[PASS] RUN ready for controlled jump after {i+1} cycles")
            return
    raise AssertionError("[FAIL] Did not reach RUN with cooldown==0")

async def wait_for_jump_entry(dut, timeout_cycles=30):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] wait_for_jump_entry requires RTL-visible state")

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) == S_JUMP:
            dut._log.info(f"[PASS] Entered S_JUMP after {i+1} cycles")
            return
    raise AssertionError("[FAIL] Jump did not enter S_JUMP")

async def wait_until_not_jump(dut, timeout_cycles=100):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] wait_until_not_jump requires RTL-visible state")

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) != S_JUMP:
            return
    raise AssertionError("[FAIL] Stayed in S_JUMP too long")


@cocotb.test()
async def test_boot_idle(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    assert uo(dut) == expected_idle_output(0), f"[FAIL] Expected idle 0xBF, got 0x{uo(dut):02X}"
    if not is_gatelevel(dut):
        assert state(dut) == S_IDLE, f"[FAIL] Expected IDLE after reset, got {state(dut)}"
        assert score(dut) == 0, f"[FAIL] Score should reset to 0, got {score(dut)}"
        assert max_score(dut) == 0, f"[FAIL] Max score should reset to 0, got {max_score(dut)}"
    dut._log.info("[PASS] Boot idle test passed")

@cocotb.test()
async def test_start_and_motion(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_start_and_motion", "GL smoke skips motion timing check")
        return

    if not is_gatelevel(dut):
        assert state(dut) in (S_RUN, S_JUMP), f"[FAIL] Expected RUN/JUMP, got {state(dut)}"
    await wait_for_output_change(dut, timeout_cycles=120, label="gameplay motion")
    dut._log.info("[PASS] Start and motion test passed")

@cocotb.test()
async def test_hit_and_score_screen(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_hit_and_score_screen", "GL smoke skips long hit/score path")
        return

    await wait_for_hit_and_score(dut)
    await wait_for_dp_toggle_in_score(dut)
    dut._log.info("[PASS] Hit and score screen test passed")

@cocotb.test()
async def test_reset_from_gameplay(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut):
        await pulse_game_reset(dut, cycles=2)
        await ClockCycles(dut.clk, 10)
        assert has_bit(uo(dut), SEG_DP), f"[FAIL] Expected idle/high-score display with DP, got 0x{uo(dut):02X}"
        dut._log.info("[PASS] Reset from gameplay test passed")
        return

    await wait_for_output_change(dut, timeout_cycles=120, label="pre-reset gameplay activity")
    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 10)
    expected = expected_idle_output(max_score(dut))
    assert state(dut) == S_IDLE, f"[FAIL] Reset from gameplay should go to IDLE, got {state(dut)}"
    assert uo(dut) == expected, f"[FAIL] Reset from gameplay should show 0x{expected:02X}, got 0x{uo(dut):02X}"
    dut._log.info("[PASS] Reset from gameplay test passed")

@cocotb.test()
async def test_reset_from_score(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_reset_from_score", "GL smoke skips long hit-to-score path")
        return

    await wait_for_hit_and_score(dut)
    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 10)

    if is_gatelevel(dut):
        assert has_bit(uo(dut), SEG_DP), f"[FAIL] Expected idle/high-score display with DP, got 0x{uo(dut):02X}"
    else:
        expected = expected_idle_output(max_score(dut))
        assert state(dut) == S_IDLE, f"[FAIL] Reset from score should go to IDLE, got {state(dut)}"
        assert uo(dut) == expected, f"[FAIL] Reset from score should show 0x{expected:02X}, got 0x{uo(dut):02X}"
    dut._log.info("[PASS] Reset from score test passed")

@cocotb.test()
async def test_difficulty_modes(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_difficulty_modes", "difficulty divider not observable in GL netlist")
        return
        
    await ClockCycles(dut.clk, 2)
    normal_frame = frame_max(dut)
    dut._log.info(f"[INFO] NORMAL frame_max={normal_frame}")

    await apply_reset(dut, difficulty_bits=0b11, seed_bits=0b1111)
    await ClockCycles(dut.clk, 2)
    insane_frame = frame_max(dut)
    dut._log.info(f"[INFO] INSANE frame_max={insane_frame}")

    assert insane_frame < normal_frame, f"[FAIL] Difficulty not applied: INSANE={insane_frame}, NORMAL={normal_frame}"
    dut._log.info("[PASS] Difficulty mode test passed")

@cocotb.test()
async def test_score_increment(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_score_increment", "GL smoke skips score-growth proof")
        return

    if is_gatelevel(dut):
        await wait_for_hit_and_score(dut)
        dut._log.info("[PASS] GL extended score path observed")
        return

    await autoplay_until_score_increase(dut, timeout_cycles=1500)
    assert score(dut) >= 1, f"[FAIL] Score did not increment, got {score(dut)}"
    dut._log.info("[PASS] Score increment test passed")

@cocotb.test()
async def test_high_score_persistence(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_high_score_persistence", "GL smoke skips long high-score persistence path")
        return

    if is_gatelevel(dut):
        await wait_for_hit_and_score(dut)
        await pulse_game_reset(dut, cycles=2)
        await ClockCycles(dut.clk, 10)
        assert has_bit(uo(dut), SEG_DP), f"[FAIL] Expected idle/high-score display with DP, got 0x{uo(dut):02X}"
        dut._log.info("[PASS] GL extended high-score smoke passed")
        return

    await autoplay_until_score_at_least(dut, target=1, timeout_cycles=5000)

    while state(dut) != S_SCORE:
        await RisingEdge(dut.clk)

    log_state(dut, "AFTER_DEATH_WITH_SCORE")
    assert max_score(dut) >= 1 or score(dut) >= 1, f"[FAIL] Expected score or max_score >=1, got score={score(dut)} max_score={max_score(dut)}"

    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 10)

    expected = expected_idle_output(max_score(dut))
    assert state(dut) == S_IDLE, f"[FAIL] Expected IDLE after reset, got {state(dut)}"
    assert uo(dut) == expected, f"[FAIL] Idle high-score display mismatch: expected 0x{expected:02X}, got 0x{uo(dut):02X}"
    assert max_score(dut) >= 1, f"[FAIL] High score did not persist, got {max_score(dut)}"
    dut._log.info("[PASS] High score persistence test passed")

@cocotb.test()
async def test_jump_cooldown(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_jump_cooldown", "GL smoke skips cooldown internal timing proof")
        return

    if is_gatelevel(dut):
        await wait_for_output_change(dut, timeout_cycles=120, label="post-start motion")
        dut._log.info("[PASS] GL extended cooldown smoke passed")
        return

    await wait_for_run_ready(dut, timeout_cycles=300)
    await pulse_jump(dut, cycles=2)
    await wait_for_jump_entry(dut, timeout_cycles=30)
    await wait_until_not_jump(dut, timeout_cycles=100)
    assert cooldown(dut) > 0, f"[FAIL] Cooldown should be >0 after jump, got {cooldown(dut)}"

    await pulse_jump(dut, cycles=2)
    await ClockCycles(dut.clk, 2)
    assert state(dut) != S_JUMP, "[FAIL] Jump should be blocked during cooldown"

    while cooldown(dut) != 0:
        await RisingEdge(dut.clk)

    while state(dut) != S_RUN:
        await RisingEdge(dut.clk)

    await pulse_jump(dut, cycles=2)
    await wait_for_jump_entry(dut, timeout_cycles=30)
    dut._log.info("[PASS] Jump cooldown test passed")

@cocotb.test()
async def test_output_sanity(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    assert uo(dut) == expected_idle_output(0), f"[FAIL] Idle output wrong: 0x{uo(dut):02X}"
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        dut._log.info("[PASS] GL smoke output sanity passed")
        return

    await ClockCycles(dut.clk, 5)
    await wait_until_not_jump(dut, timeout_cycles=100)
    
    gameplay_val = uo(dut)
    assert has_bit(gameplay_val, SEG_C), f"[FAIL] Player should be on ground (SEG_C on) during early gameplay, got 0x{gameplay_val:02X}"
    
    await wait_for_hit_and_score(dut)
    assert uo(dut) != ALL_ON, "[FAIL] Score output should not remain all-on"
    dut._log.info("[PASS] Output sanity test passed")