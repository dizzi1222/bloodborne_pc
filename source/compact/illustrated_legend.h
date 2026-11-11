// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include "bbport_atlas_style.h"
#include "bbport_map_art.h"
#include "imgui.h"
#include <algorithm>
#include <cfloat>
#include <cstdlib>
#include <cstring>
#include <utility>

enum class PassageView { Auto, Upper, Lower };

inline constexpr const char* PassageViewNames[] = {"auto", "upper", "lower"};

inline PassageView GetPassageView() {
    const char* value = std::getenv("BB_ATLAS_PASSAGE");
    if (value && std::strcmp(value, "upper") == 0) return PassageView::Upper;
    if (value && std::strcmp(value, "lower") == 0) return PassageView::Lower;
    return PassageView::Auto;
}

inline void SetPassageView(PassageView view) {
    const char* value = PassageViewNames[static_cast<int>(view)];
#ifdef _WIN32
    _putenv_s("BB_ATLAS_PASSAGE", value);
#else
    setenv("BB_ATLAS_PASSAGE", value, 1);
#endif
}

inline void CyclePassageView() {
    switch (GetPassageView()) {
    case PassageView::Auto: SetPassageView(PassageView::Upper); break;
    case PassageView::Upper: SetPassageView(PassageView::Lower); break;
    case PassageView::Lower: SetPassageView(PassageView::Auto); break;
    }
}

inline void IllustratedPickupSymbol(ImDrawList* draw, ImVec2 center, float radius,
                              ImU32 color, int shape) {
    if (!draw || radius <= 0.0f) return;
    if (shape == 0) {
        draw->AddCircleFilled(center, radius, color, 16);
    } else if (shape == 1) {
        const ImVec2 diamond[] = {{center.x, center.y - radius},
                                  {center.x + radius, center.y},
                                  {center.x, center.y + radius},
                                  {center.x - radius, center.y}};
        draw->AddConvexPolyFilled(diamond, 4, color);
    } else if (shape == 2) {
        draw->AddRectFilled({center.x - radius, center.y - radius},
                            {center.x + radius, center.y + radius}, color,
                            radius * .35f);
    } else {
        const ImVec2 hex[] = {{center.x - radius, center.y},
                              {center.x - radius * .5f, center.y - radius},
                              {center.x + radius * .5f, center.y - radius},
                              {center.x + radius, center.y},
                              {center.x + radius * .5f, center.y + radius},
                              {center.x - radius * .5f, center.y + radius}};
        draw->AddConvexPolyFilled(hex, 6, color);
    }
}

// Fixed, non-canvas map key in the reserved right artwork gutter.
inline void IllustratedLegend(ImDrawList* draw, ImFont* font,
                        const BbAtlasStyle::Layout& layout, float scale,
                        PassageView view) {
    if (!draw) return;
    if (!font) font = ImGui::GetFont();
    if (scale <= 0.0f) scale = layout.scale;

    constexpr float panel_x = 1084.0f;
    constexpr float panel_y = 120.0f;
    constexpr float panel_w = 168.0f;
    constexpr float panel_h = 520.0f;
    const ImU32 ink = IM_COL32(20, 22, 21, 248);
    const ImU32 border = IM_COL32(153, 133, 94, 220);
    const ImU32 rule = IM_COL32(153, 133, 94, 95);
    const ImU32 paper = IM_COL32(224, 218, 202, 255);
    const ImU32 muted = IM_COL32(174, 169, 155, 255);
    const ImU32 dim = IM_COL32(130, 128, 118, 255);

    auto point = [&](float x, float y) {
        const auto p = layout.At(x, y);
        return ImVec2(p.x, p.z);
    };
    auto rect = [&](float x, float y, float w, float h) {
        const ImVec2 a = point(x, y);
        const ImVec2 b = point(x + w, y + h);
        return std::pair<ImVec2, ImVec2>{a, b};
    };
    auto text = [&](const char* value, float x, float y, float size,
                    ImU32 color) {
        draw->AddText(font, size * scale, point(x, y), color, value);
    };

    const auto panel = rect(panel_x, panel_y, panel_w, panel_h);
    draw->AddRectFilled(panel.first, panel.second, ink, 4.0f * scale);
    draw->AddRect(panel.first, panel.second, border, 4.0f * scale,
                  ImDrawFlags_RoundCornersAll, 0.9f * scale);
    draw->AddRectFilled(point(panel_x + 1, panel_y + 1),
                        point(panel_x + panel_w - 1, panel_y + 3),
                        IM_COL32(205, 177, 120, 170));
    draw->PushClipRect(point(panel_x + 1, panel_y + 1),
                       point(panel_x + panel_w - 1, panel_y + panel_h - 1),
                       true);

    constexpr float title_x = panel_x + 13;
    constexpr float title_y = panel_y + 12;
    constexpr float title_size = 16.0f;
    const float key_width = font->CalcTextSizeA(title_size * scale, FLT_MAX,
                                                0.0f, "KEY").x;
    float symbols_size = 9.5f;
    const float symbols_width = font->CalcTextSizeA(symbols_size * scale,
                                                     FLT_MAX, 0.0f,
                                                     "MAP SYMBOLS").x;
    const float symbols_x = title_x + key_width / scale + 12.0f;
    const float available = panel_x + panel_w - 13.0f - symbols_x;
    if (symbols_width > available * scale && symbols_width > 0.0f)
        symbols_size *= std::max(0.0f, available * scale) / symbols_width;
    text("KEY", title_x, title_y, title_size, paper);
    text("MAP SYMBOLS", symbols_x, panel_y + 15, symbols_size, muted);
    draw->AddLine(point(panel_x + 12, panel_y + 40),
                  point(panel_x + panel_w - 12, panel_y + 40), rule,
                  0.75f * scale);

    text("NAVIGATION", panel_x + 12, panel_y + 50, 10.0f, muted);
    struct NavEntry {
        const char* icon;
        const char* label;
    };
    constexpr NavEntry navigation[] = {
        {"lamp", "Lamp"},
        {"ladder", "Ladder"},
        {"gate", "Gate / door"},
        {"talk", "NPC"},
    };
    constexpr float nav_start_y = panel_y + 72;
    constexpr float nav_row_h = 29.0f;
    for (int i = 0; i < 4; ++i) {
        const float y = nav_start_y + i * nav_row_h;
        const ImVec2 icon = point(panel_x + 25, y + 11);
        BbMapArt::DrawIcon(draw, navigation[i].icon, icon, 21.0f * scale,
                           0.0f, IM_COL32(211, 201, 177, 245));
        text(navigation[i].label, panel_x + 45, y + 3, 12.5f, paper);
    }

    draw->AddLine(point(panel_x + 12, panel_y + 194),
                  point(panel_x + panel_w - 12, panel_y + 194), rule,
                  0.75f * scale);
    text("PICKUPS", panel_x + 12, panel_y + 204, 10.0f, muted);
    struct Pickup {
        const char* label;
        ImU32 color;
        int shape;
    };
    constexpr Pickup pickups[] = {
        {"Blood vials", IM_COL32(230, 81, 76, 255), 0},
        {"Insight", IM_COL32(189, 121, 234, 255), 1},
        {"Equipment", IM_COL32(93, 172, 242, 255), 2},
        {"Coldblood", IM_COL32(235, 193, 79, 255), 3},
    };
    constexpr float pickup_start_y = panel_y + 225;
    constexpr float pickup_row_h = 27.0f;
    for (int i = 0; i < 4; ++i) {
        const ImVec2 center = point(panel_x + 25,
                                    pickup_start_y + i * pickup_row_h + 8);
        const float r = 4.5f * scale;
        IllustratedPickupSymbol(draw, center, r, pickups[i].color, pickups[i].shape);
        text(pickups[i].label, panel_x + 45,
             pickup_start_y + i * pickup_row_h + 1, 12.5f, paper);
    }

    draw->AddLine(point(panel_x + 12, panel_y + 343),
                  point(panel_x + panel_w - 12, panel_y + 343), rule,
                  0.75f * scale);
    text("PASSAGE VIEW", panel_x + 12, panel_y + 353, 10.0f, muted);

    constexpr float control_x = panel_x + 12;
    constexpr float control_y = panel_y + 374;
    constexpr float control_w = panel_w - 24;
    constexpr float control_h = 28;
    constexpr float gap = 2;
    constexpr float segment_w = (control_w - 2 * gap) / 3;
    const char* labels[] = {"Auto", "Upper", "Lower"};
    const ImGuiIO& io = ImGui::GetIO();
    for (int i = 0; i < 3; ++i) {
        const float x = control_x + i * (segment_w + gap);
        const auto bounds = rect(x, control_y, segment_w, control_h);
        const bool hovered = io.MousePos.x >= bounds.first.x &&
                             io.MousePos.x <= bounds.second.x &&
                             io.MousePos.y >= bounds.first.y &&
                             io.MousePos.y <= bounds.second.y;
        if (hovered) ImGui::SetMouseCursor(ImGuiMouseCursor_Hand);
        const bool active = static_cast<int>(view) == i;
        const ImU32 fill = active ? IM_COL32(105, 83, 47, 245)
                                  : (hovered ? IM_COL32(58, 53, 43, 245)
                                             : IM_COL32(34, 35, 32, 245));
        draw->AddRectFilled(bounds.first, bounds.second, fill, 2.0f * scale);
        draw->AddRect(bounds.first, bounds.second,
                      active ? IM_COL32(210, 177, 112, 230) : rule,
                      2.0f * scale, ImDrawFlags_RoundCornersAll,
                      0.75f * scale);
        const float label_width = font->CalcTextSizeA(10.5f * scale, FLT_MAX,
                                                       0.0f, labels[i]).x;
        const float label_x = x + (segment_w - label_width / scale) * .5f;
        text(labels[i], label_x, control_y + 7, 10.5f,
             active ? paper : (hovered ? paper : muted));
        if (hovered && ImGui::IsMouseClicked(ImGuiMouseButton_Left)) {
            SetPassageView(static_cast<PassageView>(i));
        }
    }
    text("Auto follows passage height.", panel_x + 12, panel_y + 412,
         9.5f, dim);
    text("Ordinary slopes stay", panel_x + 12, panel_y + 434, 9.5f, muted);
    text("continuous across levels.", panel_x + 12, panel_y + 448, 9.5f,
         muted);
    draw->PopClipRect();
}
