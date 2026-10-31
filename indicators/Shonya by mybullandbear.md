// This Pine Script® code is subject to the terms of the Mozilla Public License 2.0 at https://mozilla.org/MPL/2.0/
// © mybullandbear
//@version=6
indicator("MYBULLANDBEAR SHONYA", overlay=true, max_labels_count=500, max_lines_count=500, max_bars_back=500)
// ┌────────────────────────────── BOSWaves ─ Constants ──────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
const string g1 = "Core Engine"
const string g2 = "Gravity Model"
const string g3 = "Visual Style"
const string g4 = "Dashboard"
// ┌────────────────────────────── BOSWaves ─ Tooltips ───────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
const string tt_len       = "Baseline smoothing length. Higher = smoother trend, fewer flips."
const string tt_gravLen   = "Lookback for gravity detection. Lower = more reactive to acceleration shifts."
const string tt_decay     = "How fast gravity fades when acceleration drops. Higher = gravity lingers longer."
const string tt_madLen    = "MAD lookback for volatility sizing. Higher = smoother trail."
const string tt_trailMin  = "Trail distance during strong gravity. Lower = cloud hugs price tighter."
const string tt_trailMax  = "Trail distance during weak gravity. Higher = cloud drifts further from price."
const string tt_cloud     = "Show the multi-band gravity cloud beneath price in uptrends, above in downtrends."
const string tt_bars      = "Color candles by current trend direction."
const string tt_signals   = "Show Buy/Sell signal markers on trend switches."
const string tt_levels    = "Project horizontal levels from where gravity failed — the flip points."
const string tt_levelLen  = "How many bars forward the gravity-fail levels extend."
const string tt_levelW    = "Line width for gravity-fail levels."
const string tt_dots      = "Markers when price retests the gravity cloud."
const string tt_dotCD     = "Minimum bars between consecutive retest markers."
const string tt_sigBuf    = "Bars to wait after a flip before retest markers can fire."
const string tt_bg        = "Tint chart background by current trend."
const string tt_dash      = "Show a small live status dashboard in the corner."
// ┌────────────────────────────── BOSWaves ─ Inputs ─────────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
int    len          = input.int(14, "Trend Length", minval=5, group=g1, tooltip=tt_len)
int    gravLen      = input.int(19, "Gravity Lookback", minval=1, group=g2, tooltip=tt_gravLen)
float  decayRate    = input.float(0.96, "Gravity Decay", minval=0.80, maxval=0.99, step=0.01, group=g2, tooltip=tt_decay)
int    madLen       = input.int(24, "MAD Length", minval=5, group=g2, tooltip=tt_madLen)
float  trailMin     = input.float(1.0, "Trail Min (Strong Pull)", minval=0.3, step=0.1, group=g2, tooltip=tt_trailMin)
float  trailMax     = input.float(1.0, "Trail Max (Weak Pull)", minval=1.0, step=0.1, group=g2, tooltip=tt_trailMax)
bool   showCloud    = input.bool(true, "Show Gravity Cloud", group=g3, tooltip=tt_cloud)
bool   paintBars    = input.bool(true, "Color Candles", group=g3, tooltip=tt_bars)
bool   showSignals  = input.bool(true, "Show Buy/Sell Signals", group=g3, tooltip=tt_signals)
bool   showLevels   = input.bool(true, "Show Gravity Fail Levels", group=g3, tooltip=tt_levels)
int    levelLen     = input.int(50, "Level Projection Length", minval=10, group=g3, tooltip=tt_levelLen)
int    levelW       = input.int(2, "Level Line Width", minval=1, group=g3, tooltip=tt_levelW)
bool   showDots     = input.bool(true, "Retest Markers", group=g3, tooltip=tt_dots)
int    dotCooldown  = input.int(12, "Retest Cooldown", minval=0, group=g3, tooltip=tt_dotCD)
int    signalBuffer = input.int(10, "Signal Buffer Period", minval=1, maxval=30, group=g3, tooltip=tt_sigBuf)
bool   bgTint       = input.bool(true, "Background Tint", group=g3, tooltip=tt_bg)
bool   showDash     = input.bool(true, "Show Dashboard", group=g4, tooltip=tt_dash)
string dashPos      = input.string("Top Right", "Dashboard Position", options=["Top Right","Top Left","Bottom Right","Bottom Left"], group=g4)
color  bullCol      = input.color(#00E676, "Bullish Color", inline="col", group=g3)
color  bearCol      = input.color(#FF1744, "Bearish Color", inline="col", group=g3)
color  bullCol2     = input.color(#00B0FF, "Bullish Accent", inline="col2", group=g3)
color  bearCol2     = input.color(#FF6D00, "Bearish Accent", inline="col2", group=g3)
// ┌────────────────────────────── BOSWaves ─ State ──────────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
var float gravity      = 0.0
var int   lastSignal   = 0
var int   lastBullDot  = na
var int   lastBearDot  = na
var int   lastSignalBar = 0
var int   flipCount    = 0
// ┌────────────────────────────── BOSWaves ─ Core Calculations ──────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
float basisC = ta.ema(close, len)
float basis  = basisC
// Volatility — Mean Absolute Deviation
float mean = ta.sma(close, madLen)
float mad  = ta.sma(math.abs(close - mean), madLen)
// ┌────────────────────────────── BOSWaves ─ Gravity Detection ──────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
float velocity  = basis - basis[gravLen]
float accel     = velocity - nz(velocity[1])
float normAccel = mad > 0 ? math.abs(accel) / mad : 0.0
if normAccel > 0.01
    gravity := math.min(normAccel * 8.0, 2.0)
else
    gravity := gravity * decayRate
float pull = math.min(gravity / 1.5, 1.0)
// ┌────────────────────────────── BOSWaves ─ Adaptive Trail ─────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
float trailMult = trailMax - (trailMax - trailMin) * pull
float upper     = basis + mad * trailMult
float lower     = basis - mad * trailMult
// ┌────────────────────────────── BOSWaves ─ Signal Logic ───────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
bool longCond  = ta.crossover(close, upper)
bool shortCond = ta.crossunder(close, lower)
int prevSignal = lastSignal
lastSignal := longCond ? 1 : shortCond ? -1 : lastSignal
bool  switchUp   = lastSignal == 1 and prevSignal == -1
bool  switchDown = lastSignal == -1 and prevSignal == 1
color trendCol   = lastSignal == 1 ? bullCol : bearCol
color accentCol  = lastSignal == 1 ? bullCol2 : bearCol2
if switchUp or switchDown
    lastSignalBar := bar_index
    flipCount += 1
// ┌────────────────────────────── BOSWaves ─ Background Tint ────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
bgcolor(bgTint ? color.new(trendCol, 94) : na, title="Trend Background")
// ┌────────────────────────────── BOSWaves ─ Candles ────────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
color candleBody = pull > 0.6 ? accentCol : trendCol
plotcandle(open, high, low, close, "Candles",
     candleBody,
     bordercolor=trendCol,
     wickcolor=color.new(trendCol, 25),
     display=paintBars ? display.all : display.none)
// ┌────────────────────────────── BOSWaves ─ Gravity Cloud (multi-band) ─────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
float cloudThick = mad * (0.4 + 0.6 * pull)
float cloudOuter = lastSignal == 1 ? lower : upper
float cloudMid   = lastSignal == 1 ? lower + cloudThick * 0.5 : upper - cloudThick * 0.5
float cloudInner = lastSignal == 1 ? lower + cloudThick : upper - cloudThick
float cloudOuterVis = ta.ema(cloudOuter, 5)
float cloudMidVis   = ta.ema(cloudMid, 5)
float cloudInnerVis = ta.ema(cloudInner, 5)
pOuter = plot(showCloud ? cloudOuterVis : na, "Cloud Outer", color=color.new(trendCol, 15), linewidth=2)
pMid   = plot(showCloud ? cloudMidVis   : na, "Cloud Mid",   color=color.new(accentCol, 55), linewidth=1)
pInner = plot(showCloud ? cloudInnerVis : na, "Cloud Inner", color=color.new(trendCol, 75), linewidth=1)
pBasis = plot(showCloud ? basis : na, "Baseline", color=color.new(color.gray, 60), linewidth=1, style=plot.style_line)
fill(pOuter, pMid, cloudOuter, cloudMid,
     color.new(trendCol, 35), color.new(accentCol, 55), title="Cloud Fill Outer")
fill(pMid, pInner, cloudMid, cloudInner,
     color.new(accentCol, 55), color.new(trendCol, 88), title="Cloud Fill Inner")
// ┌────────────────────────────── BOSWaves ─ Gravity Fail Levels ────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
if showLevels and switchUp
    line.new(bar_index, low, bar_index + levelLen, low,
         color=color.new(bullCol, 25), style=line.style_dashed, width=levelW)
    label.new(bar_index, low, "Gravity Fail ▲", style=label.style_none,
         textcolor=color.new(bullCol, 10), size=size.tiny, xloc=xloc.bar_index)
if showLevels and switchDown
    line.new(bar_index, high, bar_index + levelLen, high,
         color=color.new(bearCol, 25), style=line.style_dashed, width=levelW)
    label.new(bar_index, high, "Gravity Fail ▼", style=label.style_none,
         textcolor=color.new(bearCol, 10), size=size.tiny, xloc=xloc.bar_index)
// ┌────────────────────────────── BOSWaves ─ Retest Markers ─────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
bool farEnough = bar_index - lastSignalBar >= signalBuffer
bool bullRetest = showDots and lastSignal == 1  and low  < cloudInner and farEnough
bool bearRetest = showDots and lastSignal == -1 and high > cloudInner and farEnough
bool bullDotOk = bullRetest and (na(lastBullDot) or bar_index - lastBullDot >= dotCooldown)
bool bearDotOk = bearRetest and (na(lastBearDot) or bar_index - lastBearDot >= dotCooldown)
if bullDotOk
    lastBullDot := bar_index
if bearDotOk
    lastBearDot := bar_index
plotchar(bullDotOk, title="Bull Retest", char="●", location=location.belowbar, color=bullCol2, size=size.tiny)
plotchar(bearDotOk, title="Bear Retest", char="●", location=location.abovebar, color=bearCol2, size=size.tiny)
// ┌────────────────────────────── BOSWaves ─ Signals ────────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
if showSignals and switchUp
    label.new(bar_index, low - mad * 1.8, "▲ LONG",
         style=label.style_label_up,
         size=size.small,
         color=color.new(bullCol, 0),
         textcolor=color.white)
if showSignals and switchDown
    label.new(bar_index, high + mad * 1.8, "▼ SHORT",
         style=label.style_label_down,
         size=size.small,
         color=color.new(bearCol, 0),
         textcolor=color.white)
// ┌────────────────────────────── BOSWaves ─ Dashboard ──────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
if showDash and barstate.islast
    string posStr = dashPos == "Top Right" ? position.top_right : dashPos == "Top Left" ? position.top_left : dashPos == "Bottom Right" ? position.bottom_right : position.bottom_left
    table dash = table.new(position=posStr, columns=2, rows=4,
         bgcolor=color.new(color.black, 15), border_width=1, border_color=color.new(color.gray, 40))
    table.cell(dash, 0, 0, "Trend", text_color=color.gray, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 1, 0, lastSignal == 1 ? "BULLISH" : "BEARISH", text_color=trendCol, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 0, 1, "Pull", text_color=color.gray, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 1, 1, str.tostring(pull * 100, "#") + "%", text_color=accentCol, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 0, 2, "Trail Mult", text_color=color.gray, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 1, 2, str.tostring(trailMult, "#.##"), text_color=color.white, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 0, 3, "Flips Total", text_color=color.gray, text_size=size.small, bgcolor=color.new(color.black, 15))
    table.cell(dash, 1, 3, str.tostring(flipCount), text_color=color.white, text_size=size.small, bgcolor=color.new(color.black, 15))
// ┌────────────────────────────── BOSWaves ─ Alerts ─────────────────────────────────┐
// └──────────────────────────────────────────────────────────────────────────────────┘
alertcondition(switchUp, "Gravity Long", "Gravity Trail LONG {{ticker}} {{interval}}")
alertcondition(switchDown, "Gravity Short", "Gravity Trail SHORT {{ticker}} {{interval}}")
alertcondition(bullDotOk or bearDotOk, "Gravity Retest", "Gravity Trail Retest {{ticker}} {{interval}}")