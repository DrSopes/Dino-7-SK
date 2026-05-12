`default_nettype none

module tt_um_dino7 (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    wire _unused = &{ena, uio_in, 1'b0};

    wire jump_btn = ui_in[0];
    wire game_rst = ui_in[1];
    wire [1:0] difficulty = ui_in[3:2];
    wire [3:0] seed = ui_in[7:4];

    reg [31:0] lfsr;

    localparam S_IDLE  = 3'd0;
    localparam S_RUN   = 3'd1;
    localparam S_JUMP  = 3'd2;
    localparam S_HIT   = 3'd3;
    localparam S_SCORE = 3'd4;

    reg [2:0] state;
    reg [3:0] score;
    reg [3:0] max_score;

    reg [23:0] clk_div;
    reg [23:0] frame_max;
    reg [23:0] speed_step;
    wire frame_tick = (clk_div >= frame_max);

    reg obs_c, obs_g, obs_f, obs_passed;
    reg [2:0] jump_timer;
    reg [2:0] cooldown_timer;
    reg [4:0] blink_timer;

    reg [23:0] init_base_speed;
    reg [23:0] init_speed_step;

    always @(difficulty) begin
        `ifdef COCOTB_SIM
            case (difficulty)
                2'b00: begin init_base_speed = 24'd10; init_speed_step = 24'd2; end
                2'b01: begin init_base_speed = 24'd8;  init_speed_step = 24'd2; end
                2'b10: begin init_base_speed = 24'd6;  init_speed_step = 24'd1; end
                default: begin init_base_speed = 24'd4; init_speed_step = 24'd1; end
            endcase
        `else
            case (difficulty)
                2'b00: begin init_base_speed = 24'd6_250_000; init_speed_step = 24'd1_000_000; end
                2'b01: begin init_base_speed = 24'd5_000_000; init_speed_step = 24'd1_000_000; end
                2'b10: begin init_base_speed = 24'd3_750_000; init_speed_step = 24'd800_000;   end
                default: begin init_base_speed = 24'd2_500_000; init_speed_step = 24'd500_000; end
            endcase
        `endif
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE;
            clk_div <= 0;
            score <= 0;
            max_score <= 0;
            obs_c <= 0;
            obs_g <= 0;
            obs_f <= 0;
            obs_passed <= 0;
            jump_timer <= 0;
            cooldown_timer <= 0;
            lfsr <= {28'hA5A5A5A, seed};
            frame_max <= init_base_speed;
            speed_step <= init_speed_step;
            blink_timer <= 0;
        end else if (game_rst) begin
            state <= S_IDLE;
            clk_div <= 0;
            score <= 0;
            obs_c <= 0;
            obs_g <= 0;
            obs_f <= 0;
            obs_passed <= 0;
            jump_timer <= 0;
            cooldown_timer <= 0;
            lfsr <= {lfsr[27:0], seed};
            frame_max <= init_base_speed;
            speed_step <= init_speed_step;
            blink_timer <= 0;
        end else begin
            clk_div <= clk_div + 1;

            if (state == S_IDLE && jump_btn) begin
                state <= S_RUN;
            end

            if (state == S_RUN && jump_btn && cooldown_timer == 0) begin
                state <= S_JUMP;
                jump_timer <= 3;
            end

            if (frame_tick) begin
                clk_div <= 0;
                lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};

                case (state)
                    S_IDLE: begin
                    end

                    S_RUN, S_JUMP: begin
                        obs_passed <= obs_f;
                        obs_f <= obs_g;
                        obs_g <= obs_c;
                        obs_c <= (lfsr[0] & lfsr[1] & lfsr[2]) & !obs_c & !obs_g;

                        if (obs_f && state == S_RUN) begin
                            state <= S_HIT;
                            blink_timer <= 5;
                            if (score > max_score)
                                max_score <= score;
                        end else begin
                            if (obs_passed && state == S_JUMP) begin
                                if (score < 9)
                                    score <= score + 1;
                                if (score[1:0] == 2'b11 && frame_max > speed_step)
                                    frame_max <= frame_max - speed_step;
                            end
                        end

                        if (state == S_JUMP) begin
                            if (jump_timer > 0) begin
                                jump_timer <= jump_timer - 1;
                            end else begin
                                state <= S_RUN;
                                cooldown_timer <= 2;
                            end
                        end else begin
                            if (cooldown_timer > 0)
                                cooldown_timer <= cooldown_timer - 1;
                        end
                    end

                    S_HIT: begin
                        if (blink_timer > 0)
                            blink_timer <= blink_timer - 1;
                        else
                            state <= S_SCORE;
                    end

                    S_SCORE: begin
                        blink_timer <= blink_timer + 1;
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

    function [6:0] seg7;
        input [3:0] val;
        begin
            case (val)
                0: seg7 = 7'b0111111;
                1: seg7 = 7'b0000110;
                2: seg7 = 7'b1011011;
                3: seg7 = 7'b1001111;
                4: seg7 = 7'b1100110;
                5: seg7 = 7'b1101101;
                6: seg7 = 7'b1111101;
                7: seg7 = 7'b0000111;
                8: seg7 = 7'b1111111;
                9: seg7 = 7'b1101111;
                default: seg7 = 7'b0000000;
            endcase
        end
    endfunction

    reg [7:0] out;
    always @(*) begin
        if (state == S_IDLE) begin
            out = {1'b1, seg7(max_score)};
        end else if (state == S_HIT) begin
            out = 8'b11111111;
        end else if (state == S_SCORE) begin
            if (blink_timer[3])
                out = {1'b1, seg7(max_score)};
            else
                out = {1'b0, seg7(score)};
        end else begin
            out[0] = obs_c;
            out[1] = obs_g;
            out[2] = (state == S_RUN);
            out[3] = obs_passed;
            out[4] = (state == S_JUMP);
            out[5] = 1'b0;
            out[6] = obs_f;
            out[7] = (cooldown_timer > 0);
        end
    end

    assign uo_out = out;

endmodule