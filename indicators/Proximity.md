// This source code is subject to the terms of the Mozilla Public License 2.0
// © LuxAlgo (original algorithm) | Enhanced v6 port
//@version=6
indicator("Moving Averages Proximity Oscillator", "PROXIMITY", max_labels_count = 500)
// ═══════════════════════════════════════════════════════════════════════════════
// INPUTS — General
// ═══════════════════════════════════════════════════════════════════════════════
const string GRP_GEN  = "⚙️ General"
const string GRP_VIS  = "🎨 Visuals"
const string GRP_SIG  = "🔔 Signals"
const string GRP_DIV  = "📐 Divergence"
i_min        = input.int   (10,    "Minimum Length",            minval = 1,  group = GRP_GEN)
i_max        = input.int   (100,   "Maximum Length",            minval = 1,  group = GRP_GEN)
i_smooth     = input.int   (9,     "Smoothing",                 minval = 1,  group = GRP_GEN)
i_normalized = input.bool  (true,  "Normalized (0–100)",                     group = GRP_GEN)
i_src        = input.source(close, "Source",                                 group = GRP_GEN)
// ─── Visuals ──────────────────────────────────────────────────────────────────
i_heatmap   = input.bool(true, "Heatmap Columns",           group = GRP_VIS)
i_bg        = input.bool(true, "Trend Strength Background", group = GRP_VIS)
i_bg_transp = input.int (88,  "Background Transparency",   minval = 50, maxval = 95, group = GRP_VIS)
// ─── Signals ──────────────────────────────────────────────────────────────────
i_signals         = input.bool(true, "Show Buy / Sell Signals",              group = GRP_SIG)
i_sig_len_rising  = input.bool(true, "Require Proximity Index Rising (Buy)", group = GRP_SIG)
i_sig_len_falling = input.bool(true, "Require Proximity Index Falling (Sell)", group = GRP_SIG)
// ─── Divergence ───────────────────────────────────────────────────────────────
i_div       = input.bool(true, "Show Divergence Labels",  group = GRP_DIV)
i_piv_left  = input.int (5,   "Pivot Lookback (Left)",   minval = 1, group = GRP_DIV)
i_piv_right = input.int (5,   "Pivot Lookback (Right)",  minval = 1, group = GRP_DIV)
// ═══════════════════════════════════════════════════════════════════════════════
// CORE MAPO CALCULATION  (original algorithm — unchanged)
// ═══════════════════════════════════════════════════════════════════════════════
csum = ta.cum(i_src)
var float len = 0.0
var float per = 0.0
float max_min = math.abs(i_src - (csum - csum[i_min]) / i_min)
per := 0.0
for i = i_min to i_max
    float ma = (csum - csum[i]) / i
    per      += i_src > ma ? 1 : 0
    float ae  = math.abs(i_src - ma)
    max_min   := math.min(ae, max_min)
    len       := ae == max_min ? i : len
len := ta.sma(len, i_smooth)
per := ta.sma(per, i_smooth)
if i_normalized
    len := (len - i_min) / (i_max - i_min + 1) * 100
    per := per  / (i_max - i_min + 1) * 100
else
    per := per + i_min
// ═══════════════════════════════════════════════════════════════════════════════
// LEVELS
// ═══════════════════════════════════════════════════════════════════════════════
float lvl = i_normalized ? 50.0 : (i_max + i_min + 1) / 2
float ob  = i_normalized ? 80.0 : 0.8 * i_max + 0.2 * i_min
float os_ = i_normalized ? 20.0 : 0.8 * i_min + 0.2 * i_max
// ═══════════════════════════════════════════════════════════════════════════════
// HEATMAP COLOR  (5-zone gradient on per)
// ═══════════════════════════════════════════════════════════════════════════════
color col_heatmap =
     per >= 80 ? color.new(#1b7a3e, 30) :  // dark green
     per >= 60 ? color.new(#4caf50, 30) :  // light green
     per >= 40 ? color.new(#f9a825, 30) :  // amber
     per >= 20 ? color.new(#e65100, 30) :  // orange
                 color.new(#b71c1c, 30)    // dark red
color col_per = i_heatmap
     ? col_heatmap
     : per > lvl ? color.new(color.teal, 50) : color.new(color.red, 50)
// ═══════════════════════════════════════════════════════════════════════════════
// TREND STRENGTH BACKGROUND
// ═══════════════════════════════════════════════════════════════════════════════
color bg_col = i_bg and per > ob  ? color.new(color.teal, i_bg_transp) :
               i_bg and per < os_ ? color.new(color.red,  i_bg_transp) : na
bgcolor(bg_col, title = "Trend Strength Background")
// ═══════════════════════════════════════════════════════════════════════════════
// BUY / SELL SIGNALS
// ═══════════════════════════════════════════════════════════════════════════════
bool len_rising  = len > len[1]
bool len_falling = len < len[1]
bool buy_cond  = ta.crossover (per, lvl) and (not i_sig_len_rising  or len_rising)
bool sell_cond = ta.crossunder(per, lvl) and (not i_sig_len_falling or len_falling)
plotshape(i_signals and buy_cond,
     title    = "Buy Signal",
     style    = shape.labelup,
     location = location.bottom,
     color    = color.new(color.teal, 10),
     text     = "B",
     textcolor = color.white,
     size     = size.small)
plotshape(i_signals and sell_cond,
     title    = "Sell Signal",
     style    = shape.labeldown,
     location = location.top,
     color    = color.new(color.red, 10),
     text     = "S",
     textcolor = color.white,
     size     = size.small)
// ═══════════════════════════════════════════════════════════════════════════════
// DIVERGENCE DETECTION  (pivot-based)
// ═══════════════════════════════════════════════════════════════════════════════
float ph_price = ta.pivothigh(i_src, i_piv_left, i_piv_right)
float pl_price = ta.pivotlow (i_src, i_piv_left, i_piv_right)
float ph_len   = ta.pivothigh(len,   i_piv_left, i_piv_right)
float pl_len   = ta.pivotlow (len,   i_piv_left, i_piv_right)
var float prev_ph_price = na
var float prev_ph_len   = na
var float prev_pl_price = na
var float prev_pl_len   = na
bool bear_div = false
if not na(ph_price)
    if not na(prev_ph_price) and not na(prev_ph_len)
        if ph_price > prev_ph_price and ph_len < prev_ph_len
            bear_div := true
    prev_ph_price := ph_price
    prev_ph_len   := ph_len
bool bull_div = false
if not na(pl_price)
    if not na(prev_pl_price) and not na(prev_pl_len)
        if pl_price < prev_pl_price and pl_len > prev_pl_len
            bull_div := true
    prev_pl_price := pl_price
    prev_pl_len   := pl_len
if i_div and bull_div
    label.new(bar_index[i_piv_right], pl_len[i_piv_right],
         text      = "Bull Div",
         style     = label.style_label_up,
         color     = color.new(color.teal, 10),
         textcolor = color.white,
         size      = size.small)
if i_div and bear_div
    label.new(bar_index[i_piv_right], ph_len[i_piv_right],
         text      = "Bear Div",
         style     = label.style_label_down,
         color     = color.new(color.red, 10),
         textcolor = color.white,
         size      = size.small)
// ═══════════════════════════════════════════════════════════════════════════════
// PLOTS
// ═══════════════════════════════════════════════════════════════════════════════
plot(per, "Price Above MA's",
     color    = col_per,
     style    = plot.style_columns,
     histbase = lvl)
plot(len, "Proximity Index",
     color     = color.new(#5b9cf6, 0),
     linewidth = 2)
hline(ob,  "Overbought", color = color.new(color.gray, 40), linestyle = hline.style_dashed)
hline(lvl, "Mid",        color = color.new(color.gray, 60), linestyle = hline.style_dotted)
hline(os_, "Oversold",   color = color.new(color.gray, 40), linestyle = hline.style_dashed)
// ═══════════════════════════════════════════════════════════════════════════════
// ALERTS
// ═══════════════════════════════════════════════════════════════════════════════
alertcondition(buy_cond,  "MAPO Buy Signal",         "MAPO: Buy — per crossed above midline.")
alertcondition(sell_cond, "MAPO Sell Signal",        "MAPO: Sell — per crossed below midline.")
alertcondition(bull_div,  "MAPO Bullish Divergence", "MAPO: Bullish divergence on Proximity Index.")
alertcondition(bear_div,  "MAPO Bearish Divergence", "MAPO: Bearish divergence on Proximity Index.")
alertcondition(per > ob,  "MAPO Overbought Zone",    "MAPO: Entered overbought zone (>80).")
alertcondition(per < os_, "MAPO Oversold Zone",      "MAPO: Entered oversold zone (<20).")