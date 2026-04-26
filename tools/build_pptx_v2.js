"use strict";

const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const TMP = path.join(__dirname, "../.tmp");
const digest = JSON.parse(fs.readFileSync(path.join(TMP, "digest.json"), "utf8"));
const channelToVideoUrl = {};
(digest.trending_videos || []).forEach(v => {
  if (!channelToVideoUrl[v.channel]) channelToVideoUrl[v.channel] = `https://youtu.be/${v.videoId}`;
});

const C = {
  darkBg:    "0B1F3A",
  midBg:     "122840",
  lightBg:   "F5F7FA",
  white:     "FFFFFF",
  accent:    "FF6B35",
  navy:      "0B1F3A",
  textLight: "EEF2FF",
  mutedDark: "B0C4D8",   // lightened for better contrast on dark bg
  muted:     "6B7280",
  border:    "E5E7EB",
  amber:     "F59E0B",
  link:      "1D6FB8",
};

const W = 13.3;
const H = 7.5;
const MARGIN_L = 0.45;  // left margin
const MARGIN_B = 0.65;  // bottom margin

const makeShadow = () => ({ type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.08 });

function trunc(str, len) {
  if (!str) return "";
  return str.length > len ? str.substring(0, len - 1) + "…" : str;
}

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";

// ── HELPER: dark header bar ───────────────────────────────────────────────────
function headerBar(slide, title, subtitle) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: W, h: 0.95,
    fill: { color: C.darkBg }, line: { color: C.darkBg },
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0.94, w: W, h: 0.05,
    fill: { color: C.accent }, line: { color: C.accent },
  });
  slide.addText(title, {
    x: 0.5, y: 0.1, w: 10, h: 0.52,
    fontSize: 26, bold: true, color: C.white, fontFace: "Calibri", margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.5, y: 0.61, w: 11.5, h: 0.27,
      fontSize: 11, color: C.mutedDark, fontFace: "Calibri", margin: 0,
    });
  }
}

// ── SLIDE 1: COVER ────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };

  // Left accent stripe
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.28, h: H,
    fill: { color: C.accent }, line: { color: C.accent },
  });

  // Title block (left side)
  slide.addText("AI INDUSTRY", {
    x: 0.62, y: 1.3, w: 6.8, h: 1.0,
    fontSize: 60, bold: true, color: C.white, fontFace: "Calibri", charSpacing: 3,
  });
  slide.addText("WEEKLY DIGEST", {
    x: 0.62, y: 2.24, w: 6.8, h: 0.9,
    fontSize: 48, bold: true, color: C.accent, fontFace: "Calibri", charSpacing: 3,
  });
  const weekDate = new Date(digest._meta?.generated_at || Date.now())
    .toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
  slide.addText(`Week of ${weekDate}`, {
    x: 0.62, y: 3.25, w: 6.8, h: 0.38,
    fontSize: 15, color: C.mutedDark, fontFace: "Calibri",
  });
  slide.addText("AI Vendor News  ·  YouTube Trends  ·  Prompt Tips  ·  Tools & Signals", {
    x: 0.62, y: 3.72, w: 6.8, h: 0.32,
    fontSize: 12, color: "7A9CBD", fontFace: "Calibri",
  });

  // Right side — stat callouts
  const stats = [
    { num: `${(digest.top_stories || []).length}`, label: "TOP STORIES" },
    { num: `${(digest.trending_videos || []).length}`, label: "TRENDING VIDEOS" },
    { num: `${(digest.prompt_tips || []).length}`, label: "PROMPT TIPS" },
    { num: `${(digest.tools_setups || []).length}`, label: "TOOLS & SETUPS" },
  ];
  const statX = 8.1;
  const statW = 4.8;
  const statH = 1.2;
  const statGap = 0.2;
  const statStartY = (H - (stats.length * statH + (stats.length - 1) * statGap)) / 2;

  stats.forEach((s, i) => {
    const sy = statStartY + i * (statH + statGap);
    slide.addShape(pres.shapes.RECTANGLE, {
      x: statX, y: sy, w: statW, h: statH,
      fill: { color: C.midBg }, line: { color: "1A3A5C", width: 1 },
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: statX, y: sy, w: 0.07, h: statH,
      fill: { color: C.accent }, line: { color: C.accent },
    });
    slide.addText(s.num, {
      x: statX + 0.2, y: sy + 0.12, w: 1.1, h: 0.72,
      fontSize: 44, bold: true, color: C.accent, fontFace: "Calibri", align: "center", margin: 0,
    });
    slide.addText(s.label, {
      x: statX + 1.4, y: sy + 0.38, w: statW - 1.55, h: 0.35,
      fontSize: 13, bold: true, color: C.textLight, fontFace: "Calibri", margin: 0,
    });
  });

  // Footer
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: H - 0.45, w: W, h: 0.45,
    fill: { color: "060F1D" }, line: { color: "060F1D" },
  });
  slide.addText("Automated briefing — WAT Framework + Claude + PptxGenJS", {
    x: 0.62, y: H - 0.38, w: W - 1, h: 0.3,
    fontSize: 9.5, color: "6B8EAE", fontFace: "Calibri",
  });
}

// ── SLIDE 2: EXECUTIVE SUMMARY ────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };
  headerBar(slide, "Executive Summary", "What you need to know this week");

  const bullets = digest.executive_summary || [];
  const gapY = 0.09;
  const totalH = H - 1.18 - MARGIN_B;
  const itemH = (totalH - gapY * (bullets.length - 1)) / bullets.length;

  bullets.forEach((text, i) => {
    const y = 1.18 + i * (itemH + gapY);
    slide.addShape(pres.shapes.RECTANGLE, {
      x: MARGIN_L, y, w: W - MARGIN_L * 2, h: itemH,
      fill: { color: C.midBg }, line: { color: "1A3A5C", width: 1 },
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: MARGIN_L, y, w: 0.07, h: itemH,
      fill: { color: C.accent }, line: { color: C.accent },
    });
    slide.addText(`0${i + 1}`, {
      x: MARGIN_L + 0.12, y: y + itemH / 2 - 0.22, w: 0.44, h: 0.44,
      fontSize: 15, bold: true, color: C.accent, fontFace: "Calibri",
      align: "center", margin: 0,
    });
    slide.addText(text, {
      x: MARGIN_L + 0.7, y: y + 0.1, w: W - MARGIN_L * 2 - 0.75, h: itemH - 0.2,
      fontSize: 14.5, color: C.textLight, fontFace: "Calibri", margin: 0,
    });
  });
}

// ── SLIDES 3+: TOP STORIES ────────────────────────────────────────────────────
{
  const stories = digest.top_stories || [];
  const perPage = 3;
  const totalPages = Math.ceil(stories.length / perPage);
  const CARD_H = 1.9;
  const gapY = 0.12;
  const blocksH = perPage * CARD_H + (perPage - 1) * gapY;
  const startY = 1.08 + (H - 1.08 - MARGIN_B - blocksH) / 2;

  for (let p = 0; p < stories.length; p += perPage) {
    const chunk = stories.slice(p, p + perPage);
    const pageNum = Math.floor(p / perPage) + 1;
    const slide = pres.addSlide();
    slide.background = { color: C.lightBg };
    headerBar(slide, "Top Stories",
      `Major announcements from AI providers  ·  ${pageNum} of ${totalPages}`);

    chunk.forEach((story, i) => {
      const y = startY + i * (CARD_H + gapY);
      slide.addShape(pres.shapes.RECTANGLE, {
        x: MARGIN_L, y, w: W - MARGIN_L * 2, h: CARD_H,
        fill: { color: C.white }, line: { color: C.border, width: 1 },
        shadow: makeShadow(),
      });
      slide.addShape(pres.shapes.RECTANGLE, {
        x: MARGIN_L, y, w: 0.06, h: CARD_H,
        fill: { color: C.accent }, line: { color: C.accent },
      });

      const cx = MARGIN_L + 0.2;
      const cw = W - MARGIN_L * 2 - 0.25;

      slide.addText((story.provider || "").toUpperCase(), {
        x: cx, y: y + 0.1, w: 4, h: 0.26,
        fontSize: 9.5, bold: true, color: C.amber, fontFace: "Calibri", margin: 0,
      });

      // Headline — clickable
      slide.addText([{
        text: trunc(story.headline || "", 100),
        options: { hyperlink: { url: story.url }, bold: true, color: C.navy, fontSize: 16 },
      }], {
        x: cx, y: y + 0.33, w: cw, h: 0.45,
        fontFace: "Calibri", margin: 0,
      });

      slide.addText(trunc(story.why_it_matters || "", 200), {
        x: cx, y: y + 0.82, w: cw, h: 0.7,
        fontSize: 13, color: C.muted, fontFace: "Calibri", margin: 0,
      });

      if (story.url) {
        slide.addText([{
          text: story.url,
          options: { hyperlink: { url: story.url }, color: C.link, fontSize: 8.5 },
        }], {
          x: cx, y: y + CARD_H - 0.28, w: cw, h: 0.24,
          fontFace: "Calibri", margin: 0,
        });
      }
    });
  }
}

// ── SLIDE: TRENDING YOUTUBE ───────────────────────────────────────────────────
{
  const vids = (digest.trending_videos || []).slice(0, 6);
  if (vids.length) {
    const slide = pres.addSlide();
    slide.background = { color: C.lightBg };
    headerBar(slide, "Trending on YouTube", "From your curated channel list — click any card to watch");

    const cols = 3, rows = 2, gapX = 0.14, gapY = 0.16;
    const startX = MARGIN_L, startY = 1.08;
    const cardW = (W - startX * 2 - gapX * (cols - 1)) / cols;
    const cardH = (H - startY - MARGIN_B - gapY * (rows - 1)) / rows;
    const thumbH = cardH * 0.44;

    vids.forEach((v, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = startX + col * (cardW + gapX);
      const y = startY + row * (cardH + gapY);
      const videoUrl = `https://youtu.be/${v.videoId}`;
      const thumbUrl = `https://img.youtube.com/vi/${v.videoId}/mqdefault.jpg`;

      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: cardW, h: cardH,
        fill: { color: C.white }, line: { color: C.border, width: 1 },
        shadow: makeShadow(),
      });

      slide.addImage({
        path: thumbUrl,
        x: x + 0.04, y: y + 0.04, w: cardW - 0.08, h: thumbH,
        hyperlink: { url: videoUrl },
      });

      const tY = y + thumbH + 0.1;
      const remainH = cardH - thumbH - 0.14;

      slide.addText([{
        text: trunc(v.title || "", 75),
        options: { hyperlink: { url: videoUrl }, bold: true, color: C.navy, fontSize: 10.5 },
      }], {
        x: x + 0.1, y: tY, w: cardW - 0.2, h: 0.5,
        fontFace: "Calibri", margin: 0,
      });

      slide.addText(`${v.channel || ""}  ·  ${(v.views || 0).toLocaleString()} views`, {
        x: x + 0.1, y: tY + 0.5, w: cardW - 0.2, h: 0.25,
        fontSize: 8.5, color: C.muted, fontFace: "Calibri", margin: 0,
      });

      slide.addText(trunc(v.key_takeaway || "", 130), {
        x: x + 0.1, y: tY + 0.75, w: cardW - 0.2, h: remainH - 0.75,
        fontSize: 8.5, color: "374151", fontFace: "Calibri", margin: 0,
      });
    });
  }
}

// ── SLIDE: PROMPT TIPS ────────────────────────────────────────────────────────
{
  const tips = (digest.prompt_tips || []).slice(0, 4);
  if (tips.length) {
    const slide = pres.addSlide();
    slide.background = { color: C.lightBg };
    headerBar(slide, "Prompt & Setup Tips", "Distilled from video transcripts — click source to watch");

    const cols = 2, gapX = 0.3, gapY = 0.18;
    const startX = MARGIN_L;
    const startY = 1.08;
    const CARD_H = (H - startY - MARGIN_B - gapY) / 2;
    const cardW = (W - startX * 2 - gapX) / cols;

    tips.forEach((tip, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = startX + col * (cardW + gapX);
      const y = startY + row * (CARD_H + gapY);
      const videoUrl = channelToVideoUrl[tip.source_channel];

      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: cardW, h: CARD_H,
        fill: { color: C.white }, line: { color: C.border, width: 1 },
        shadow: makeShadow(),
      });
      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: cardW, h: 0.05,
        fill: { color: C.accent }, line: { color: C.accent },
      });

      slide.addText(trunc(tip.tip || "", 160), {
        x: x + 0.18, y: y + 0.14, w: cardW - 0.36, h: 0.95,
        fontSize: 13, color: C.navy, fontFace: "Calibri", margin: 0,
      });

      if (tip.example) {
        slide.addText(`e.g. ${trunc(tip.example, 100)}`, {
          x: x + 0.18, y: y + 1.16, w: cardW - 0.36, h: 0.55,
          fontSize: 9, color: C.muted, italic: true, fontFace: "Calibri", margin: 0,
        });
      }

      const sourceRuns = videoUrl
        ? [{ text: `↗ ${tip.source_channel}`, options: { hyperlink: { url: videoUrl }, color: C.accent, bold: true, fontSize: 9.5 } }]
        : [{ text: tip.source_channel || "", options: { color: C.muted, fontSize: 9.5 } }];
      slide.addText(sourceRuns, {
        x: x + 0.18, y: y + CARD_H - 0.32, w: cardW - 0.36, h: 0.26,
        fontFace: "Calibri", margin: 0,
      });
    });
  }
}

// ── SLIDE: TOOLS & SETUPS ─────────────────────────────────────────────────────
{
  const tools = (digest.tools_setups || []).slice(0, 4);
  if (tools.length) {
    const slide = pres.addSlide();
    slide.background = { color: C.lightBg };
    headerBar(slide, "Tools & Setups Worth Trying", "Hands-on recommendations — click source to watch");

    const cols = 2, gapX = 0.3, gapY = 0.18;
    const startX = MARGIN_L;
    const startY = 1.08;
    const CARD_H = (H - startY - MARGIN_B - gapY) / 2;
    const cardW = (W - startX * 2 - gapX) / cols;

    tools.forEach((tool, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = startX + col * (cardW + gapX);
      const y = startY + row * (CARD_H + gapY);
      const videoUrl = channelToVideoUrl[tool.source];

      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: cardW, h: CARD_H,
        fill: { color: C.white }, line: { color: C.border, width: 1 },
        shadow: makeShadow(),
      });

      slide.addShape(pres.shapes.OVAL, {
        x: x + 0.15, y: y + 0.17, w: 0.42, h: 0.42,
        fill: { color: C.accent }, line: { color: C.accent },
      });
      slide.addText(`${i + 1}`, {
        x: x + 0.15, y: y + 0.19, w: 0.42, h: 0.38,
        fontSize: 13, bold: true, color: C.white, fontFace: "Calibri", align: "center", margin: 0,
      });

      slide.addText(trunc(tool.tool_or_setup || "", 60), {
        x: x + 0.7, y: y + 0.15, w: cardW - 0.86, h: 0.46,
        fontSize: 15, bold: true, color: C.navy, fontFace: "Calibri", margin: 0,
      });

      slide.addText(trunc(tool.use_case || "", 160), {
        x: x + 0.18, y: y + 0.7, w: cardW - 0.36, h: 1.05,
        fontSize: 13, color: "374151", fontFace: "Calibri", margin: 0,
      });

      const sourceRuns = videoUrl
        ? [{ text: `↗ ${tool.source}`, options: { hyperlink: { url: videoUrl }, color: C.accent, bold: true, fontSize: 9.5 } }]
        : [{ text: tool.source || "", options: { color: C.muted, fontSize: 9.5 } }];
      slide.addText(sourceRuns, {
        x: x + 0.18, y: y + CARD_H - 0.32, w: cardW - 0.36, h: 0.26,
        fontFace: "Calibri", margin: 0,
      });
    });
  }
}

// ── SLIDE: INDUSTRY SIGNALS ───────────────────────────────────────────────────
{
  const signals = digest.industry_signals || [];
  if (signals.length) {
    const slide = pres.addSlide();
    slide.background = { color: C.darkBg };
    headerBar(slide, "Industry Signals", "Big picture trends from this week's content");

    const cols = 2, gapX = 0.2, gapY = 0.18;
    const startX = MARGIN_L;
    const startY = 1.08;
    const CARD_H = (H - startY - MARGIN_B - gapY) / 2;
    const cardW = (W - startX * 2 - gapX) / cols;

    signals.slice(0, 4).forEach((sig, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = startX + col * (cardW + gapX);
      const y = startY + row * (CARD_H + gapY);

      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: cardW, h: CARD_H,
        fill: { color: C.midBg }, line: { color: "1A3A5C", width: 1 },
      });
      slide.addShape(pres.shapes.RECTANGLE, {
        x, y, w: 0.06, h: CARD_H,
        fill: { color: C.accent }, line: { color: C.accent },
      });

      slide.addText(trunc(sig.signal || "", 80), {
        x: x + 0.22, y: y + 0.14, w: cardW - 0.32, h: 0.52,
        fontSize: 14.5, bold: true, color: C.textLight, fontFace: "Calibri", margin: 0,
      });
      slide.addText(trunc(sig.evidence || "", 200), {
        x: x + 0.22, y: y + 0.72, w: cardW - 0.32, h: CARD_H - 0.85,
        fontSize: 12.5, color: C.mutedDark, fontFace: "Calibri", margin: 0,
      });
    });
  }
}

// ── SLIDE: OUTRO ──────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.darkBg };

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.28, h: H,
    fill: { color: C.accent }, line: { color: C.accent },
  });

  slide.addText("See you next week.", {
    x: 0.62, y: 1.4, w: 11, h: 1.0,
    fontSize: 52, bold: true, color: C.white, fontFace: "Calibri",
  });
  slide.addText("This digest is automated via the WAT framework.", {
    x: 0.62, y: 2.52, w: 9, h: 0.4,
    fontSize: 16, color: C.mutedDark, fontFace: "Calibri",
  });

  // Horizontal rule
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.62, y: 3.08, w: W - 0.62 - 0.45, h: 0.03,
    fill: { color: "1A3A5C" }, line: { color: "1A3A5C" },
  });

  // Top stories as clickable links in lower section
  slide.addText("THIS WEEK'S STORIES", {
    x: 0.62, y: 3.3, w: 5, h: 0.3,
    fontSize: 10, bold: true, color: C.accent, fontFace: "Calibri", charSpacing: 2, margin: 0,
  });

  const outroStories = (digest.top_stories || []).slice(0, 4);
  outroStories.forEach((story, i) => {
    slide.addText([{
      text: `${String(i + 1).padStart(2, "0")}  ${trunc(story.headline || "", 80)}`,
      options: { hyperlink: { url: story.url }, color: "7EC8E3", fontSize: 14 },
    }], {
      x: 0.62, y: 3.75 + i * 0.72, w: W - 0.62 - 0.45, h: 0.55,
      fontFace: "Calibri", margin: 0,
    });
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: H - 0.45, w: W, h: 0.45,
    fill: { color: "060F1D" }, line: { color: "060F1D" },
  });
  slide.addText("Generated with Claude · PptxGenJS · WAT Framework", {
    x: 0.62, y: H - 0.38, w: W - 1, h: 0.3,
    fontSize: 9.5, color: "6B8EAE", fontFace: "Calibri",
  });
}

// ── WRITE FILE ────────────────────────────────────────────────────────────────
const today = new Date().toISOString().split("T")[0];
const outPath = path.join(TMP, `ai_digest_${today}.pptx`);

pres.writeFile({ fileName: outPath })
  .then(() => {
    console.log(`Done. Written: ${outPath}`);
    console.log(`Slides: ${pres.slides.length}`);
  })
  .catch(err => {
    console.error("Error:", err.message);
    process.exit(1);
  });
