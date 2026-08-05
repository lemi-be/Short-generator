9:16 Video Layout Specifications

All outputs are rendered to a standardized mobile canvas size:


$$\text{Resolution} = 1080 \times 1920\text{ pixels}$$

$$\text{Aspect Ratio} = 9:16 \quad \left(\frac{9}{16} = 0.5625\right)$$

Template 1: Stage & Solo Speaker (Preaching, Stand-up, Keynotes)

1. Canvas Dimensions & Scaling

Final Output Size: $1080 \times 1920\text{ px}$

Source Crop Box ($16:9$ Source): $608 \times 1080\text{ px}$ region extracted from the full $1920 \times 1080$ source video.

Scale Factor: $\approx 1.777\times$ scaling from source crop to output canvas.

2. Visual Layout Breakdown

 0px  +-----------------------------------+
      |      TOP SAFE ZONE (No Text)      |  <- 0px to 441px (23% height)
      |  (Hook Title / Top Headline)      |     Reserved for UI overlays
441px +-----------------------------------+
      |                                   |
      |                                   |
      |          PRIMARY STAGE            |  <- 441px to 1593px (60% height)
      |          SPEAKER FOCUS            |     Smooth camera tracking zone
      |         (1080 x 1152 px)          |     centered on head & torso
      |                                   |
      |                                   |
1180px|  [ DYNAMIC WORD-BY-WORD CAPTION ] |  <- 1180px to 1500px
1593px+-----------------------------------+
      |      BOTTOM UI SAFE ZONE          |  <- 1593px to 1920px (17% height)
      |  (Speaker Name / Handle Tag)      |     Prevents TikTok/Reels caption
1920px+-----------------------------------+     and like button overlap


3. Key Framing Rules

Subject Position: Speaker’s head is kept strictly inside the top third of the frame ($y \approx 350\text{ px}$ to $550\text{ px}$).

Caption Position: Centered at $y = 1330\text{ px}$ with a font size scaled to cover no more than $80\%$ of the canvas width ($864\text{ px}$).

Template 2: Podcast & Dialogue (Stacked 50/50 Split-Screen)

1. Canvas Dimensions & Panel Ratios

Final Output Size: $1080 \times 1920\text{ px}$

Top Panel (Host/Speaker 1): $1080 \times 960\text{ px}$ (Panel Aspect Ratio $9:8 = 1.125$)

Bottom Panel (Guest/Speaker 2): $1080 \times 960\text{ px}$ (Panel Aspect Ratio $9:8 = 1.125$)

Source Crop Box ($16:9$ Source per speaker): $1215 \times 1080\text{ px}$ region, scaled down to $1080 \times 960\text{ px}$.

2. Visual Layout Breakdown

 0px  +-----------------------------------+
      |                                   |
      |            TOP PANEL              |  <- 0px to 960px (Panel Size: 1080x960 px)
      |         HOST / SPEAKER 1          |     Aspect Ratio: 9:8
      |                                   |
 958px+-----------------------------------+  <- 2px to 4px accent divider line
 962px+-----------------------------------+     or subtle 50% opacity border
      |                                   |
      |           BOTTOM PANEL            |  <- 960px to 1920px (Panel Size: 1080x960 px)
      |        GUEST / SPEAKER 2          |     Aspect Ratio: 9:8
      |                                   |
1920px+-----------------------------------+


3. Subtitle Overlay Placement Strategies

Option A (Center Divider Overlay): Place dynamic captions directly across the middle split ($y = 860\text{ px}$ to $1060\text{ px}$) over a semi-transparent dark banner background.

Option B (Lower-Third Overlay): Place captions near the bottom of the lower frame ($y = 1500\text{ px}$ to $1700\text{ px}$).

Summary Comparison Matrix

Layout Metric

Stage / Solo Speaker

Podcast Split-Screen

Output Aspect Ratio

$9:16$ ($1080 \times 1920\text{ px}$)

$9:16$ ($1080 \times 1920\text{ px}$)

Number of Active Viewports

$1$ Full-height panel

$2$ Stacked $9:8$ panels

Crop Aspect per Viewport

$9:16$ ($608 \times 1080\text{ px}$ source)

$9:8$ ($1215 \times 1080\text{ px}$ source per panel)

Caption Position

Lower-middle ($y \approx 1350\text{ px}$)

Center divide ($y \approx 960\text{ px}$) or lower ($y \approx 1600\text{ px}$)

Distortion Check

Zero stretching

Zero stretching