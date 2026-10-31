//
@version=
5
indicator(title=" Hull Suite", shorttitle="MYUBULLANDNEAR RF x Hull", overlay=true)
selectedSession = input.string("No filter", options=["No filter", "New York", "London", "Tokyo", "Sydney"], title="Filter entry signals & alerts by session")
grp_CS          = "Candlesticks"
colorEntrybar   = input(true, title="Show entry candles", group=grp_CS, inline="el")
markEntrybar    = input(true, title="Arrow", group=grp_CS, inline="el")
entryLabels     = input(false, title="Label", group=grp_CS, inline="el")
showRanging     = input(true, title="Color consolidation candles", group=grp_CS, tooltip="Determined by the Range Filter settings as ranging/consolidating mid-range")
allCandleColor  = input(true, title="Color trending candles", group=grp_CS, tooltip="Determined by the Range Filter settings as not ranging/consolidating")
grp_MAIN        = "General"
showWatermark   = input(true, title="Show watermark", group=grp_MAIN)
enableSessions  = input(false, title="Show sessions", group=grp_MAIN)
showHullRibbon  = input(true, title="Show Hull ribbon", group=grp_MAIN)
showRF          = input(false, title="Show Range Filter", group=grp_MAIN)
showRFBands     = input(false, title="Show Range Filter bands", group=grp_MAIN)
grp_MAVE        = "Moving averages"
enableMA        = input(false, title="Show moving averages", group=grp_MAVE)
enableMTFMA     = input(false, title="Show MTF moving average levels", group=grp_MAVE, tooltip="This will show up to three moving average for different timeframes, defaults are set to the 144 ema, and the 3m, 5m and 15m timeframes.")
tripleMAFilter  = input(false, title="Triple moving average trend filter", group=grp_MAVE, tooltip="This will use 3 moving averages, short, mid and long, to detect trend when they 
are lined up one above the other in order for buys, and in reverse order for sells.\n\nIt is for the purpose of avoiding trades when price may likely be consolidating.")
showMATrendRibbon=input(false, title="Triple moving average trend ribbon", group=grp_MAVE, tooltip="This will show a ribbon at the bottom of the chart when the 3 moving averages are trending one above the other in order.")
// Color variables
grp_THEME = "Theme"
upColor   = input.color(color.rgb(0, 225, 255), title="Bullish*", group=grp_THEME, tooltip="This will be applied to entry candles, the Range Filter, and the Hull ribbon. These are not always technically bullish candles, but rather derive their logic from the Range Filter bar coloring instead of OHLC values.")
downColor = input.color(color.rgb(226, 2, 107), title="Bearish*", group=grp_THEME, tooltip="This will be applied to entry candles, the Range Filter, and the Hull ribbon. These are not always technically bearish candles, but rather derive their logic from the Range Filter bar coloring instead of OHLC values.")
midColor  = input.color(color.orange, title="Consolidation candle", group=grp_THEME, tooltip="Determined by the Range Filter settings as ranging")
// //=Moving averages
// //==================================================================================================================================
ma(length, type) =>
    switch type
        "SMA" => ta.sma(close, length)
        "EMA" => ta.ema(close, length)
        "SMMA (RMA)" => ta.rma(close, length)
        "WMA" => ta.wma(close, length)
        "VWMA" => ta.vwma(close, length)
        "HULLMA" => ta.wma(2*ta.wma(close, length/2)-ta.wma(close, length), math.floor(math.sqrt(length)))
grp_MA      = "Moving average"
ma1color    = input(color.new(color.orange, 40), title="", group=grp_MA, inline="1")
lenMA1      = input(144, title="", group=grp_MA, inline="1")
typeMA1     = input.string(title = "", defval = "EMA", options=["EMA", "SMA", "SMMA (RMA)", "WMA", "VWMA", "HULLMA"], group=grp_MA, inline="1")
showma1     = input(true, title="Show long", group=grp_MA, inline="1")
ma2color    = input(color.new(color.blue, 40), title="", group=grp_MA, inline="2")
lenMA2      = input(50, title="", group=grp_MA, inline="2")
typeMA2     = input.string(title = "", defval = "EMA", options=["EMA", "SMA", "SMMA (RMA)", "WMA", "VWMA", "HULLMA"], group=grp_MA, inline="2")
showma2     = input(true, title="Show mid", group=grp_MA, inline="2")
ma3color    = input(color.new(color.red, 40), title="", group=grp_MA, inline="3")
lenMA3      = input(21, title="", group=grp_MA, inline="3")
typeMA3     = input.string(title = "", defval = "EMA", options=["EMA", "SMA", "SMMA (RMA)", "WMA", "VWMA", "HULLMA"], group=grp_MA, inline="3")
showma3     = input(true, title="Show short", group=grp_MA, inline="3")
plot(showma1 and enableMA ? ma(lenMA1, typeMA1) : na, title="MA 1", color = ma1color, linewidth=1, display = display.pane)
plot(showma2 and enableMA ? ma(lenMA2, typeMA2) : na, title="MA 2", color = ma2color, linewidth=1, display = display.pane)
plot(showma3 and enableMA ? ma(lenMA3, typeMA3) : na, title="MA 3", color = ma3color, linewidth=1, display = display.pane)
bullishtrend = (ma(lenMA1, typeMA1) < ma(lenMA2, typeMA2) and ma(lenMA2, typeMA2) < ma(lenMA3, typeMA3)) ? true : false
bearishtrend = (ma(lenMA1, typeMA1) > ma(lenMA2, typeMA2) and ma(lenMA2, typeMA2) > ma(lenMA3, typeMA3)) ? true : false
//=MTF MA settings
//==================================================================================================================================
grp_MTFMA   = "MTF MA Settings"
MTFMALen    = input.int(144, title="", minval=2, maxval=200, step=1, group=grp_MTFMA, inline="0")
MTFMAType   = input.string("EMA", title="", options=["SMA", "EMA", "SMMA (RMA)", "WMA", "VWMA", "HULLMA"], group=grp_MTFMA, inline="0")
realPriceTicker = ticker.new(prefix=syminfo.prefix, ticker=syminfo.ticker)
getTimeframe(timeframe) =>
    switch timeframe
        "1m" => "1"
        "2m" => "2"
        "3m" => "3"
        "5m" => "5"
        "10m" => "10"
        "15m" => "15"
// MTF MA #1
tf1LineColor    = input.color(color.new(color.orange, 40), title="", group=grp_MTFMA, inline='1')
tf1             = input.string("3m", title="", options=["1m", "2m", "3m", "5m", "10m", "15m"], group=grp_MTFMA, inline='1')
enableTF1       = input.bool(true, title='Show Level', group=grp_MTFMA, inline='1', tooltip="")
// MTF MA #2 
tf2LineColor    = input.color(color.new(color.orange, 40), title="", group=grp_MTFMA, inline='2')
tf2             = input.string("5m", title="", options=["1m", "2m", "3m", "5m", "10m", "15m"], group=grp_MTFMA, inline='2')
enableTF2       = input.bool(true, title='Show Level', group=grp_MTFMA, inline='2')
// MTF MA #3 
tf3LineColor    = input.color(color.new(color.orange, 40), title='', group=grp_MTFMA, inline='3')
tf3             = input.string("15m", title='', options=["1m", "2m", "3m", "5m", "10m", "15m"], group=grp_MTFMA, inline='3')
enableTF3       = input.bool(true, title='Show Level', group=grp_MTFMA, inline='3')
mtf1MA          = request.security(symbol=realPriceTicker, timeframe=getTimeframe(tf1), expression=ma(MTFMALen, MTFMAType), lookahead=barmerge.lookahead_off, gaps=barmerge.gaps_off)
mtf2MA          = request.security(symbol=realPriceTicker, timeframe=getTimeframe(tf2), expression=ma(MTFMALen, MTFMAType), lookahead=barmerge.lookahead_off, gaps=barmerge.gaps_off)
mtf3MA          = request.security(symbol=realPriceTicker, timeframe=getTimeframe(tf3), expression=ma(MTFMALen, MTFMAType), lookahead=barmerge.lookahead_off, gaps=barmerge.gaps_off)
mtfMATextColor  = input.color(color.new(color.orange, 60), title="", group=grp_MTFMA, inline="4")
showTFLabel     = input.bool(true, title='Show Timeframe Labels', group=grp_MTFMA, inline="4")
if (enableMTFMA and enableTF1)
    mtf1MALine = line.new(x1=bar_index, x2=bar_index + 10, y1=mtf1MA, y2=mtf1MA, extend=extend.right, style=line.style_dotted, color=tf1LineColor)
    line.delete(mtf1MALine[1])
    if(showTFLabel)
        mtf1MALabel = label.new(x=(bar_index + 20), y=mtf1MA, style=label.style_label_down, text=tf1, color=na, textcolor=mtfMATextColor)
        label.delete(mtf1MALabel[1])
if(enableMTFMA and enableTF2)
    mtf2MALine = line.new(x1=bar_index, x2=bar_index + 10, y1=mtf2MA, y2=mtf2MA, extend=extend.right, style=line.style_dotted, color=tf2LineColor)
    line.delete(mtf2MALine[1])
    if(showTFLabel)
        mtf2MALabel = label.new(x=(bar_index + 20), y=mtf2MA, style=label.style_label_down, text=tf2, color=na, textcolor=mtfMATextColor)
        label.delete(mtf2MALabel[1])
if(enableMTFMA and enableTF3)
    mtf3MALine = line.new(x1=bar_index, x2=bar_index + 10, y1=mtf3MA, y2=mtf3MA, extend=extend.right, style=line.style_dotted, color=tf3LineColor)
    line.delete(mtf3MALine[1])
    if(showTFLabel)
        mtf3MALabel = label.new(x=(bar_index + 20), y=mtf3MA, style=label.style_label_down, text=tf3, color=na, textcolor=mtfMATextColor)
        label.delete(mtf3MALabel[1])
//=Range Filter
//==================================================================================================================================
grp_RF = "Range Filter"
src = input(defval=hl2, title="Source", group=grp_RF)
per = input.int(defval=24, minval=1, title="Sampling Period", group=grp_RF)
mult = input.float(defval=2.7, minval=0.1, title="Range Multiplier", group=grp_RF)
// Smooth Average Range
smoothrng(x, t, m) =>
    wper = t * 2 - 1
    avrng = ta.ema(math.abs(x - x[1]), t)
    smoothrng = ta.ema(avrng, wper) * m
    smoothrng
smrng = smoothrng(src, per, mult)
// Range Filter
rngfilt(x, r) =>
    rngfilt = x
    rngfilt := x > nz(rngfilt[1]) ? x - r < nz(rngfilt[1]) ? nz(rngfilt[1]) : x - r : 
       x + r > nz(rngfilt[1]) ? nz(rngfilt[1]) : x + r
    rngfilt
filt = rngfilt(src, smrng)
// Filter Direction
upward = 0.0
upward := filt > filt[1] ? nz(upward[1]) + 1 : filt < filt[1] ? 0 : nz(upward[1])
downward = 0.0
downward := filt < filt[1] ? nz(downward[1]) + 1 : filt > filt[1] ? 0 : nz(downward[1])
// Target Bands
hband = filt + smrng
lband = filt - smrng
// Colors
filtcolor = upward > 0 ? upColor : downward > 0 ? downColor : midColor
barcolor = src > filt and src > src[1] and upward > 0 ? (allCandleColor ? upColor : na) :
   src > filt and src < src[1] and upward > 0 ? (allCandleColor ? upColor : na) : 
   src < filt and src < src[1] and downward > 0 ? (allCandleColor ? downColor : na) : 
   src < filt and src > src[1] and downward > 0 ? (allCandleColor ? downColor : na) : (showRanging ? midColor : na)
isUpColor = src > filt and src > src[1] and upward > 0 ? true :
   src > filt and src < src[1] and upward > 0 ? true : false
isDownColor = src < filt and src < src[1] and downward > 0 ? true : 
   src < filt and src > src[1] and downward > 0 ? true : false
isOrange = src > filt and src > src[1] and upward > 0 ? na :
   src > filt and src < src[1] and upward > 0 ? na : 
   src < filt and src < src[1] and downward > 0 ? na : 
   src < filt and src > src[1] and downward > 0 ? na : true
filtplot = plot(filt, color=filtcolor, linewidth=2, title="Range Filter", display=(showRF ? display.all : display.none))
barcolor(barcolor)
// Target
hbandplot = plot(hband, color=color.new(upColor, 70), title="High Target", display=(showRFBands ? display.all : display.none))
lbandplot = plot(lband, color=color.new(downColor, 70), title="Low Target", display=(showRFBands ? display.all : display.none))
// Fills
fill(hbandplot, filtplot, color=color.new(upColor, 90), title="High Target Range", display=(showRFBands ? display.all : display.none))
fill(lbandplot, filtplot, color=color.new(downColor, 90), title="Low Target Range", display=(showRFBands ? display.all : display.none))
// Break Outs
longCond = bool(na)
shortCond = bool(na)
longCond := src > filt and src > src[1] and upward > 0 or 
   src > filt and src < src[1] and upward > 0
shortCond := src < filt and src < src[1] and downward > 0 or 
   src < filt and src > src[1] and downward > 0
CondIni = 0
CondIni := longCond ? 1 : shortCond ? -1 : CondIni[1]
longCondition = longCond and CondIni[1] == -1
shortCondition = shortCond and CondIni[1] == 1
//Alerts
alertcondition(longCondition, title="Range Filter buy alert on RF+ Hull", message="Range Filter buy alert on RF+ Hull")
alertcondition(shortCondition, title="Range Filter sell alert on RF+ Hull", message="Range Filter sell alert on RF+ Hull")
alertcondition(longCondition or shortCondition, title="Range Filter buy/sell alert on RF+ Hull", message="Range Filter buy/sell alert on RF+ Hull")
//=Hull Suite
//==================================================================================================================================
// INPUT
grp_HULL = "Hull Suite"
source = input(close, title="Hull Source", group=grp_HULL)
modeSwitch = input.string("Ehma", title="Hull Variation", options=["Hma", "Thma", "Ehma"], group=grp_HULL)
length = input(34, title="Length", group=grp_HULL, tooltip="180-200 for floating S/R , 55 for swing entry")
lengthMult = input(2.0, title="Length multiplier", group=grp_HULL, tooltip="Used to view higher timeframes with straight band")
useHtf = input(false, title="Show Hull MA from higher timeframe", group=grp_HULL)
htf = input.string("240", title="Higher timeframe", group=grp_HULL)
switchColor = true //input(true, "Color Hull according to trend?", group=grp_HULL)
// candleCol = input(false,title="Color candles based on Hull's Trend?", group=grp_HULL)
visualSwitch = true // = input(true, title="Show as a Band?", group=grp_HULL)
thicknesSwitch = 1// input(1, title="Line Thickness", group=grp_HULL)
transpSwitch = input.int(80, title="Band Transparency", group=grp_HULL)
// FUNCTIONS
// HMA
HMA(_src, _length) =>  ta.wma(2 * ta.wma(_src, _length / 2) - ta.wma(_src, _length), math.round(math.sqrt(_length)))
// EHMA    
EHMA(_src, _length) =>  ta.ema(2 * ta.ema(_src, _length / 2) - ta.ema(_src, _length), math.round(math.sqrt(_length)))
// THMA    
THMA(_src, _length) =>  ta.wma(ta.wma(_src,_length / 3) * 3 - ta.wma(_src, _length / 2) - ta.wma(_src, _length), _length)
    
// SWITCH
Mode(modeSwitch, src, len) =>
      modeSwitch == "Hma"  ? HMA(source, len) :
      modeSwitch == "Ehma" ? EHMA(source, len) : 
      modeSwitch == "Thma" ? THMA(source, len/2) : na
// OUT
_hull = Mode(modeSwitch, source, int(length * lengthMult))
HULL = useHtf ? request.security(syminfo.ticker, htf, _hull) : _hull
MHULL = HULL[0]
SHULL = HULL[2]
// COLOR
hullColor = switchColor ? (HULL > HULL[2] ? color.new(upColor, transpSwitch - 20) : color.new(downColor, transpSwitch - 20)) : color.new(#ff9800, 80)
// PLOT
///< Frame
Fi1 = plot(MHULL, title="MHULL", color=hullColor, linewidth=thicknesSwitch, display=(showHullRibbon ? display.pane : display.none))
Fi2 = plot(visualSwitch and showHullRibbon ? SHULL : na, title="SHULL", color=hullColor, linewidth=thicknesSwitch, display=(showHullRibbon ? display.pane : display.none))
alertcondition(ta.crossover(MHULL, SHULL), title="Hull trending up on RF+ Hull", message="Hull trending up on RF+ Hull")
alertcondition(ta.crossover(SHULL, MHULL), title="Hull trending down on RF+ Hull", message="Hull trending down on RF+ Hull")
///< Ending Filler
fill(Fi1, Fi2, title="Band Filler", color=color.new(hullColor, transpSwitch))
///BARCOLOR
// barcolor(color = candleCol ? (switchColor ? hullColor : na) : na) // << We'll use barcolor from the Range Filter instead of this one from Hull in this RF-x-Hull indicator
//=Sessions
//==================================================================================================================================
london_color    = color.new(color.green, 90)
newyork_color   = color.new(color.blue, 90)
tokyo_color     = color.new(color.red, 90)
sydney_color    = color.new(color.orange, 90)
// Show sessions
grp_SESS        = "Sessions"
utcsetting      = input.string(title="Select UTC timezone", defval="UTC+1", options=["UTC-11","UTC-10","UTC-9","UTC-8","UTC-7","UTC-6","UTC-5","UTC-4","UTC-3","UTC-2:30","UTC-2","UTC-1","UTC","UTC+1","UTC+2","UTC+3","UTC+4","UTC+4:30","UTC+5","UTC+6","UTC+7","UTC+8","UTC+9","UTC+10","UTC+11","UTC+12","UTC+13"], group=grp_SESS)
daylightsavings = input(false, title="Add 1hr for daylight savings time (DST)", group=grp_SESS)
// Show sessions
timelondon  = time(timeframe.period, daylightsavings ? "0800-1700:23456" : "0700-1600:23456", utcsetting)
timenewyork = time(timeframe.period, daylightsavings ? "1300-2200:23456" : "1200-2100:23456", utcsetting)
timetokyo   = time(timeframe.period, daylightsavings ? "0000-0900:23456" : "2300-0800:23456", utcsetting)
timesydney  = time(timeframe.period, daylightsavings ? "2200-0700:23456" : "2100-0600:23456", utcsetting)
// Show Trading Sessions
// London Session
londonsessioncolor  = input.color(london_color, title="", group=grp_SESS, inline="1")
showlondonsession   = input(false, title="Show London session", group=grp_SESS, inline="1")
bgcolor((enableSessions and timelondon and showlondonsession) ? londonsessioncolor : na)
// New York Session
newyorksessioncolor = input.color(newyork_color, title="", group=grp_SESS, inline="2")
shownewyorksession  = input(true, title="Show New York session", group=grp_SESS, inline="2")
bgcolor((enableSessions and timenewyork and shownewyorksession) ? newyorksessioncolor : na)
// Tokyo Session
tokyosessioncolor   = input.color(tokyo_color, title="", group=grp_SESS, inline="3")
showtokyosession    = input(false, title="Show Tokyo session", group=grp_SESS, inline="3")
bgcolor((enableSessions and timetokyo and showtokyosession) ? tokyosessioncolor : na)
// Sydney Session
sydneysessioncolor  = input.color(sydney_color, title="", group=grp_SESS, inline="4")
showsydneysession   = input(false, title="Show Sydney session", group=grp_SESS, inline="4")
bgcolor((enableSessions and timesydney and showsydneysession) ? sydneysessioncolor : na)
_selectedSession = switch selectedSession
    "London" => timelondon
    "New York" => timenewyork
    "Tokyo" => timetokyo
    "Sydney" => timesydney
    "No filter" => time(timeframe.period, "0000-2359:1234567", utcsetting)
lng = tripleMAFilter ? (_selectedSession and isOrange[1] and not isOrange and HULL > HULL[2] and isUpColor and bullishtrend) : _selectedSession and isOrange[1] and not isOrange and HULL > HULL[2] and isUpColor
srt = tripleMAFilter ? (_selectedSession and isOrange[1] and not isOrange and HULL < HULL[2] and isDownColor and bearishtrend) : _selectedSession and isOrange[1] and not isOrange and HULL < HULL[2] and isDownColor
plotchar(lng ? true : false, color=upColor, char="
▴
", location = location.belowbar, size=size.small, display=(markEntrybar and not entryLabels ? display.all : display.none))
plotchar(srt ? true : false, color=downColor, char="
▾
", location = location.abovebar, size=size.small, display=(markEntrybar and not entryLabels ? display.all : display.none))
plotshape(lng ? true : false, color=upColor, textcolor=color.white, text="Long", location = location.belowbar, style=shape.labelup, size=size.tiny, display=(markEntrybar and entryLabels ? display.all : display.none))
plotshape(srt ? true : false, color=downColor, textcolor=color.white, text="Short", location = location.abovebar, style=shape.labeldown, size=size.tiny, display=(markEntrybar and entryLabels ? display.all : display.none))
barcolor(srt ? (colorEntrybar ? downColor : na) : (lng ? (colorEntrybar ? upColor : na) : na))
alertcondition(lng, title="Entry candle - Bullish on RF+ Hull", message="Entry candle - Bullish on RF+ Hull")
alertcondition(srt, title="Entry candle - Bearish on RF+ Hull", message="Entry candle - Bearish on RF+ Hull")
alertcondition(lng or srt, title="Entry candle - Bull/Bear on RF+ Hull", message="Entry candle - Bull/Bear on RF+ Hull")
plotchar(bar_index, title="Trend ribbon", color=(showMATrendRibbon ? (bullishtrend ? color.new(upColor, 50) : (bearishtrend ? color.new(downColor, 50) : color.new(midColor, 50))) : na), char="
■
", location=location.bottom)
//=Watermark
//==================================================================================================================================
textVPosition = input.string("top", "", options = ["top", "middle", "bottom"], group = "Watermark text", inline="w0")
showText      = input(false, title="Show Text", group = "Watermark text", inline="w0")
s_title       = input.string("normal", "", options = ["small", "normal", "large", "huge", "auto"], group = "Watermark text", inline="w1")
c_title       = input.color(color.new(#00e1ff, 0), "", group = "Watermark text", inline="w1")
title         = input("I 
❤
", "", group = "Watermark text", inline="w1")
s_subtitle    = input.string("normal", "", options = ["small", "normal", "large", "huge", "auto"], group = "Watermark text", inline="w2")
c_subtitle    = input(color.new(#00e1ff, 0), "", group = "Watermark text", inline="w2")
subtitle      = input("N Y", "", group = "Watermark text", inline="w2")
symVPosition  = input.string("bottom", "", options = ["top", "middle", "bottom"], group = "Watermark symbol", inline="w3")
showSymText   = input(true, title="Show Symbol", group = "Watermark symbol", inline="w3")
symInfo       = syminfo.ticker  + " | " + timeframe.period + (timeframe.isminutes ? "M" : na)
date          = str.tostring(dayofmonth(time_close)) + "/" + str.tostring(month(time_close)) + "/" + str.tostring(year(time_close))
s_symInfo     = input.string("normal", "", options = ["small", "normal", "large", "huge", "auto"], group = "Watermark symbol", inline="w4")
c_symInfo     = input(color.new(#00e1ff, 0), "", group = "Watermark symbol", inline="w4")
c_bg          = color.new(color.blue, 100)
//text watermark creation
textWatermark = table.new(textVPosition + "_" + "center", 1, 3)
if showText == true and showWatermark
    table.cell(textWatermark, 0, 0, title, 0, 0, c_title, "center", text_size = s_title, bgcolor = c_bg)
    table.cell(textWatermark, 0, 1, subtitle, 0, 0, c_subtitle, "center", text_size = s_subtitle, bgcolor = c_bg)
//symbol info watermark creation
symWatermark = table.new(symVPosition + "_" + "center", 5, 5)
if showSymText == true and showWatermark
    table.cell(symWatermark, 0, 1, symInfo, 0, 0, c_symInfo, "center", text_size = s_symInfo, bgcolor = c_bg)
// TO USE AS A STRATEGY
// _____________________________________________________________________
//
// 1) Replace the word 'indicator' with the word 'strategy' on line 2 (or uncomment one of the strategy functions below line 2).
// 2) Uncomment the code below, and save.
// 3) Adjust the strategy settings at the bottom of the 'inputs' tab, and the new 'properties' tab, within the settings menu.
//
// Uncomment the code below this line...
// _____________________________________________________________________
// grp_STRAT   = "Strategy settings"
// timeInput   = input.time(timestamp("1 Nov 2022 00:00 +0000"), title="Start date", group=grp_STRAT)
// tpInPips    = input.int(100, title="TP (in pips)", group=grp_STRAT)
// slInPips    = input.int(20, title="SL (in pips)", group=grp_STRAT)
// timePeriod  = time >= timeInput
// longSignal = isOrange[1] and not isOrange and close > close[1] and HULL > HULL[2] ? true : false
// shortSignal = isOrange[1] and not isOrange and close < close[1] and HULL < HULL[2] ? true : false
// checkTrend = true
// if(tripleMAFilter)
//     if(longSignal and timePeriod and _selectedSession and bullishtrend)
//         strategy.entry("Long", strategy.long)
//         strategy.exit("Exit long", "Long", loss=slInPips, profit=tpInPips)
//     if(shortSignal and timePeriod and _selectedSession and bearishtrend)
//         strategy.entry("Short", strategy.short)
//         strategy.exit("Exit short", "Short", loss=slInPips, profit=tpInPips)
// else
//     if(longSignal and timePeriod and _selectedSession)
//         strategy.entry("Long", strategy.long)
//         strategy.exit("Exit long", "Long", loss=slInPips, profit=tpInPips)
//     if(shortSignal and timePeriod and _selectedSession)
//         strategy.entry("Short", strategy.short)
//         strategy.exit("Exit short", "Short", loss=slInPips, profit=tpInPips)