// Desk Calendar stand: a mini bench oscilloscope that the Pi + screen + audio
// HAT stack and the two speakers slot into.
//
// Body coordinates: X = left to right, Y = front to back, Z = up, origin at the
// front bottom left corner of the case. Every feature of the body is an
// extrusion that starts at the front face, so it prints face down, no supports.
//
// Export one part at a time:  openscad -D 'part="body"' -o body.stl deskcal_stand.scad
// (build.sh does all of them.)

part = "assembly"; // assembly, body, back, handle, knob_big, knob_small, clip, bnc, lock, fit_test

// ---- Hardware (from the Waveshare drawings; check against yours) -----------

// Waveshare 3.5inch DSI LCD (H), landscape, USB-C edge of the Pi facing down.
lens_w = 88.87;      // cover glass
lens_h = 52.56;
pcb_w  = 86.5;       // display PCB (centred behind the glass)
pcb_h  = 56.0;
va_w   = 75.6;       // viewable area
va_h   = 45.36;
va_left = 9.44;      // glass edge to viewable area on the wide (USB-A) end
va_bot  = 3.6;
disp_t  = 5.7;       // front of the glass to the back of the display PCB

// 8 ohm 5 W box speakers, standing on end and firing out through the sides.
spk_len = 102;       // top to bottom, including the mounting ears and the wire stub
spk_w   = 45;        // front to back, including the mounting ears
spk_t   = 21;

// ---- Fit ---------------------------------------------------------------

wall   = 2.4;
face_t = 2.0;
fit    = 0.3;        // sliding clearance
top_clear = 1.3;     // lift room above the display PCB (must exceed lip_bot)
lip_bot = 1.0;       // how far the shelf lip rises behind the display PCB
lip_top = 0.9;       // how far the roof lip overlaps the display PCB at rest
lip_gap = 0.25;      // play between the display PCB and the lips
// Retaining features only where the back of the display PCB is clear of
// standoffs and parts, measured from the left end of the PCB.
shelf_x = [29, 67];
toplip_x = [29, 55];
usbc_x = 75.3;       // USB-C port centre, same datum

// ---- Case ----------------------------------------------------------------

D = 66;              // depth of the case without the back panel
r_out = 4;
tilt = 18;           // degrees the screen leans back
ribbon_gap = 10;     // room for the DSI ribbon loop past the SD-card end
part_t = 1.6;        // speaker bay partition
win_m = 0.8;         // window margin around the viewable area
bev = 1.0;           // window bevel
eng = 0.6;           // engraving depth
bp_t = 2.0;          // back panel thickness
skirt_h = 5;

bay_x = spk_t + 2 * fit;
pcb_inset = (lens_w - pcb_w) / 2;
pcb_over = (pcb_h - lens_h) / 2;

// The case is as wide as it needs to be on the right (ribbon + speaker), and
// the left is padded so the window ends up centred.
win_l = va_left - win_m;
win_r = va_left + va_w + win_m;
right_of_lens = lens_w - pcb_inset + ribbon_gap + part_t + bay_x + wall;
lens_x = right_of_lens - (win_l + win_r);
W = lens_x + right_of_lens;
H = 2 * wall + spk_len + 0.8;

roof_in = H - wall;
z_top = roof_in - top_clear;     // top edge of the display PCB at rest
z_pb = z_top - pcb_h;            // bottom edge of the display PCB
lens_z = z_pb + pcb_over;
pcb_x = lens_x + pcb_inset;
z_sh = z_pb - 0.1;               // shelf surface
y_lip = face_t + disp_t + lip_gap;

spk_y0 = 7.5;                    // front of the speaker
side_cx = (lens_x + win_l - bev) / 2;   // centre of the strips beside the window
strip_z = 24;                    // centre line of the control strip
knob_dx = 31;

// Feet: the desk is a plane under the case, tilted about X.
foot_yf = 5;
foot_yr = D + 10;
foot_hr = 2.5;
foot_hf = foot_hr + (foot_yr - foot_yf) * tan(tilt);
function desk_z(y) = -foot_hf + (y - foot_yf) * tan(tilt);

// Handle pivot and where the grip bar rests on the roof.
piv = [52, H - 9];
bar = [9, H + 4.2];
h_len = norm(bar - piv);
h_ang = atan2(bar[1] - piv[1], bar[0] - piv[0]);
h_gap = 0.5;
h_arm = 4;
h_th = 6;
h_bar = 9;
pin_w = 5.5;
pin_l = h_gap + wall;            // flush inside, so the pins clear the speakers
piv_d = 8.6;

shaft_d = 6.0;
groove_d = 3.8;
groove_w = 1.3;
shaft_l = face_t + 2 * fit;
bnc_peg = 8.1;
bnc_len = 8;

font = "Arial:style=Bold";
$fn = 40;

assert(lens_x - fit >= wall + bay_x + part_t + 1, "left speaker bay runs into the screen");
assert(top_clear > lip_bot + 0.1, "not enough lift room to clear the shelf lip");

// ---- Helpers ---------------------------------------------------------------

// Extrude a 2D shape drawn in (x, z) from y0 to y1.
module ext_y(y0, y1) {
    translate([0, y1, 0]) rotate([90, 0, 0]) linear_extrude(y1 - y0) children();
}

// Extrude a 2D shape drawn in (y, z) from x0 to x1.
module ext_x(x0, x1) {
    translate([x0, 0, 0]) rotate([90, 0, 90]) linear_extrude(x1 - x0) children();
}

module rrect(x0, y0, x1, y1, r) {
    hull() for (x = [x0 + r, x1 - r], y = [y0 + r, y1 - r]) translate([x, y]) circle(r);
}

module slot(x0, y0, x1, y1) {
    d = min(x1 - x0, y1 - y0);
    rrect(x0, y0, x1, y1, d / 2 - 0.01);
}

module label(t, x, z, s) {
    translate([x, z]) text(t, size = s, font = font, halign = "center", valign = "center");
}

module ticks(x, z, r) {
    for (a = [-135 : 27 : 135])
        translate([x, z]) rotate(-a) translate([0, r]) square([0.8, 2.2], center = true);
}

// ---- Body ------------------------------------------------------------------

module window_2d(grow = 0) {
    rrect(lens_x + win_l - grow, lens_z + va_bot - win_m - grow,
          lens_x + win_r + grow, lens_z + va_bot + va_h + win_m + grow, 1.5 + grow);
}

knob_big_x = [W / 2 - knob_dx, W / 2, W / 2 + knob_dx];
knob_small_x = [side_cx, W - side_cx];
knob_small_z = H - 37.6;
bnc_x = [17, W - 17];

module face_holes_2d() {
    for (x = knob_big_x) translate([x, strip_z]) circle(d = shaft_d + 0.5);
    for (x = knob_small_x) translate([x, knob_small_z]) circle(d = shaft_d + 0.5);
    for (x = bnc_x) translate([x, strip_z]) circle(d = bnc_peg + 0.1);
}

module face_engrave_2d() {
    // Bezel line around the screen.
    difference() {
        window_2d(bev + 2.2);
        window_2d(bev + 1.4);
    }
    label("DESKCAL", side_cx, H - 14.6, 4.2);
    label("LA-35", W - side_cx, H - 14.6, 4.2);
    label("INTEN", knob_small_x[0], knob_small_z + 12, 3.2);
    label("TRIG", knob_small_x[1], knob_small_z + 12, 3.2);
    label("VOLTS/DIV", knob_big_x[0], 6.5, 3.2);
    label("POSITION", knob_big_x[1], 6.5, 3.2);
    label("TIME/DIV", knob_big_x[2], 6.5, 3.2);
    label("CH1", bnc_x[0], 6.5, 3.2);
    label("CH2", bnc_x[1], 6.5, 3.2);
    for (x = knob_big_x) ticks(x, strip_z, 15.2);
}

module side_vents_2d() {
    for (z = [12 : 5 : H - 13.5]) slot(12, z - 1.1, 42, z + 1.1);
    translate(piv) circle(d = piv_d);
}

module floor_vents_2d() {
    for (x = [44 : 6 : W - 44]) slot(x - 1.3, 16, x + 1.3, 52);
}

// Shelf the display PCB sits on, with a lip that rises behind it.
module shelf() {
    y1 = y_lip + lip_bot + 0.7;
    ext_x(pcb_x + shelf_x[0], pcb_x + shelf_x[1]) polygon([
        [face_t - 0.1, z_sh - wall], [face_t - 0.1, z_sh], [y_lip, z_sh],
        [y_lip + lip_bot, z_sh + lip_bot], [y1, z_sh + lip_bot], [y1, z_sh - wall]]);
    for (x = [shelf_x[0], (shelf_x[0] + shelf_x[1]) / 2 - part_t / 2, shelf_x[1] - part_t])
        ext_x(pcb_x + x, pcb_x + x + part_t) polygon([
            [face_t - 0.1, z_sh - wall + 0.1], [y1, z_sh - wall + 0.1], [face_t - 0.1, z_sh - wall - 9]]);
}

// Lip hanging from the roof behind the top edge of the display PCB.
module top_lip() {
    t = top_clear + lip_top;
    ext_x(pcb_x + toplip_x[0], pcb_x + toplip_x[1]) polygon([
        [y_lip, roof_in + 0.1], [y_lip, roof_in], [y_lip + 2, roof_in - t],
        [y_lip + 2.6, roof_in - t], [y_lip + 2.6, roof_in + 0.1]]);
}

// Short ribs that centre the glass left to right. The left pair straddles the
// LCD flex, which wraps around that end.
module lens_ribs() {
    y1 = face_t + 1.8;
    xl = lens_x - fit;
    xr = lens_x + lens_w + fit;
    ext_y(face_t - 0.1, y1) {
        translate([xl - part_t, lens_z + 2]) square([part_t, 15]);
        translate([xl - part_t, lens_z + lens_h - 6.5]) square([part_t, 5]);
        translate([xr, lens_z + 8]) square([part_t, lens_h - 16]);
    }
}

module speaker_bays() {
    xl = wall + bay_x;
    xr = W - wall - bay_x;
    // Partitions that hold the speakers against the side vents.
    ext_y(face_t - 0.1, spk_y0 + spk_w + 1) {
        translate([xl, wall - 0.1]) square([part_t, H - 2 * wall + 0.2]);
        translate([xr - part_t, wall - 0.1]) square([part_t, H - 2 * wall + 0.2]);
    }
    // Front stops at mid height, clear of the mounting ears.
    ext_y(face_t - 0.1, spk_y0) {
        for (x = [wall - 0.1, xl - 5, xr, W - wall - 4.9]) translate([x, 40]) square([5, 14]);
    }
}

module feet() {
    for (x = [16, W - 30]) {
        // Front legs.
        ext_x(x, x + 14) polygon([[0, 0.1], [0, desk_z(0)], [10, desk_z(10)], [16, 0.1]]);
        // Rear feet, which reach past the back so a tap on the screen can't tip it.
        yb = D - 18;
        ext_x(x, x + 14) polygon([[yb + desk_z(yb), 0.1], [yb, desk_z(yb)],
                                  [foot_yr + 2, desk_z(foot_yr + 2)], [foot_yr + 2, 0], [D, 0], [D, 0.1]]);
    }
    // Bail bar joining the front legs.
    ext_x(29, W - 29) polygon([[0, desk_z(0)], [6, desk_z(6)], [6, desk_z(6) + 5], [0, desk_z(0) + 5]]);
}

module detent_2d(z, s) {
    y = D - skirt_h / 2;
    polygon([[y - 1.1, z], [y, z + s * 0.55], [y + 1.1, z]]);
}

module body() {
    difference() {
        union() {
            difference() {
                ext_y(0, D) rrect(0, 0, W, H, r_out);
                ext_y(face_t, D + 1) rrect(wall, wall, W - wall, H - wall, r_out - wall);
            }
            shelf();
            top_lip();
            lens_ribs();
            speaker_bays();
            feet();
        }
        // Window, bevelled on the outside so the bezel doesn't crowd the touch area.
        hull() {
            ext_y(-0.01, 0.01) window_2d(bev);
            ext_y(bev, bev + 0.01) window_2d();
        }
        ext_y(bev, face_t + 0.2) window_2d();
        ext_y(-1, face_t + 1) face_holes_2d();
        ext_y(-0.01, eng) face_engrave_2d();
        ext_x(-1, wall + 0.5) side_vents_2d();
        ext_x(W - wall - 0.5, W + 1) side_vents_2d();
        translate([0, 0, -1]) linear_extrude(wall + 1.5) floor_vents_2d();
        // Grooves the back panel clicks into.
        ext_x(W / 2 - 28, W / 2 + 28) {
            detent_2d(roof_in - 0.01, 1);
            detent_2d(wall + 0.01, -1);
        }
    }
}

// A slice of the body around the screen, to check the display fit in a short print.
module fit_test() {
    intersection() {
        body();
        translate([lens_x - 6, -1, z_sh - 14]) cube([lens_w + 12, 14, H]);
    }
}

// ---- Back panel --------------------------------------------------------------

module back_panel() {
    c = 0.25;
    sk = 1.6;
    cable_x = pcb_x + usbc_x;
    difference() {
        union() {
            ext_y(D, D + bp_t) rrect(0, 0, W, H, r_out);
            difference() {
                ext_y(D - skirt_h, D + 0.1) rrect(wall + c, wall + c, W - wall - c, H - wall - c, r_out - wall);
                ext_y(D - skirt_h - 1, D + 0.01)
                    rrect(wall + c + sk, wall + c + sk, W - wall - c - sk, H - wall - c - sk, 0.5);
            }
            ext_x(W / 2 - 25, W / 2 + 25) {
                detent_2d(roof_in - c - 0.01, 0.8);
                detent_2d(wall + c + 0.01, -0.8);
            }
            // Posts that keep the speakers pushed forward.
            ext_y(spk_y0 + spk_w + 0.6, D + 0.1)
                for (x = [wall + bay_x / 2, W - wall - bay_x / 2])
                    translate([x - 3, H / 2 - 7]) square([6, 14]);
        }
        // Power cable, below the Pi's USB-C port. Open at the bottom so the
        // panel lifts off with the cable still plugged in.
        ext_y(D - skirt_h - 1, D + bp_t + 1) hull() {
            translate([cable_x - 7.5, -1]) square([15, 1]);
            translate([cable_x, 10]) circle(d = 15);
        }
        ext_y(D - 1, D + bp_t + 1)
            for (x = [W / 2 - 36 : 6 : W / 2 + 36]) slot(x - 1.3, H - 47.6, x + 1.3, H - 11.6);
    }
}

// ---- Handle --------------------------------------------------------------------

module handle_2d() {
    wi = W + 2 * h_gap;
    difference() {
        rrect(-h_arm, -5, wi + h_arm, h_len + h_bar / 2, 5);
        rrect(0, -20, wi, h_len - h_bar / 2, 2);
    }
    translate([-0.1, -pin_w / 2]) square([pin_l + 0.1, pin_w]);
    translate([wi - pin_l, -pin_w / 2]) square([pin_l + 0.1, pin_w]);
}

module handle() {
    linear_extrude(h_th) handle_2d();
}

module handle_placed() {
    translate([-h_gap, piv[0], piv[1]]) rotate([h_ang, 0, 0])
        translate([0, 0, -h_th / 2]) handle();
}

// ---- Knobs, clips and jacks (all modelled as printed, front face down) ----------

module knob(d, h) {
    fl = 1.6;
    n = round(d * 0.9);
    difference() {
        union() {
            cylinder(d1 = d - 1.2, d2 = d, h = 0.6);
            translate([0, 0, 0.6]) cylinder(d = d, h = h - fl - 0.6);
            translate([0, 0, h - fl - 2]) cylinder(d1 = d, d2 = d + 4, h = 2);
            translate([0, 0, h - fl]) cylinder(d = d + 4, h = fl);
            translate([0, 0, h]) cylinder(d = groove_d, h = shaft_l + groove_w + 0.1);
            translate([0, 0, h]) cylinder(d = shaft_d, h = shaft_l);
            translate([0, 0, h + shaft_l + groove_w]) cylinder(d1 = groove_d, d2 = shaft_d, h = 1.1);
            translate([0, 0, h + shaft_l + groove_w + 1.1]) cylinder(d = shaft_d, h = 0.6);
        }
        for (i = [0 : n - 1])
            rotate(i * 360 / n) translate([d / 2 + 0.5, 0, -1]) cylinder(d = 2, h = h - fl - 1, $fn = 12);
        translate([-0.7, d / 2 - d * 0.38, -0.01]) cube([1.4, d * 0.38 + 1, 0.6]);
    }
}

module knob_big() { knob(20, 11); }
module knob_small() { knob(13, 9); }

// Slides into the groove on a knob shaft from inside the case; the knob then spins freely.
module clip() {
    difference() {
        cylinder(d = 10, h = groove_w - 0.2);
        translate([0, 0, -1]) cylinder(d = groove_d + 0.3, h = 3);
        translate([0, -(groove_d - 0.4) / 2, -1]) cube([10, groove_d - 0.4, 3]);
    }
}

// Dummy BNC jack. Pushes into the face from the front; a dab of glue holds it.
module bnc() {
    difference() {
        union() {
            cylinder(d = 9.6, h = bnc_len);
            translate([0, 0, bnc_len - 1.7]) cylinder(d1 = 9.6, d2 = 13, h = 1.7);
            translate([0, 0, bnc_len]) cylinder(d = 13, h = 1.4, $fn = 6);
            translate([0, 0, bnc_len + 1.4]) cylinder(d = bnc_peg, h = face_t);
            for (a = [0, 180]) rotate(a) translate([4.5, 0, 3.2]) rotate([0, 90, 0]) cylinder(d = 2.2, h = 1.3, $fn = 16);
        }
        difference() {
            translate([0, 0, -0.01]) cylinder(d = 6.8, h = 5.5);
            cylinder(d = 2.2, h = 5.5);
        }
    }
}

module on_face(x, z, h) {
    translate([x, -h - fit, z]) rotate([-90, 0, 0]) children();
}

// ---- Optional lock ---------------------------------------------------------------

// A fork that slides in under the roof from the back, either side of the roof
// lip, and fills the lift room so the display can't be bumped off its shelf.
module lock() {
    t = top_clear - 0.3;
    y0 = face_t + 0.5;
    y1 = D - skirt_h - 1;
    translate([pcb_x, 0, z_top + 0.1]) linear_extrude(t) {
        translate([8, y0]) square([14, y1 - y0]);
        translate([60, y0]) square([14, y1 - y0]);
        translate([8, y_lip + 7]) square([66, y1 - y_lip - 7]);
    }
}

// ---- Stand-ins for the electronics (assembly view only) ------------------------------

module electronics() {
    y_pi = face_t + disp_t + 5;
    color("#111") translate([lens_x, face_t, lens_z]) cube([lens_w, 1.8, lens_h]);
    color("#2a7fff") translate([lens_x + va_left, face_t - 0.05, lens_z + va_bot]) cube([va_w, 0.1, va_h]);
    color("#888") translate([lens_x + 1, face_t + 1.8, lens_z + 0.5]) cube([lens_w - 2, 2.3, lens_h - 1]);
    color("#1a4a9a") translate([pcb_x, face_t + 4.1, z_pb]) cube([pcb_w, 1.6, pcb_h]);
    color("#2e8b3d") translate([pcb_x + 1.5, y_pi, z_pb]) cube([85, 1.4, 56]);
    color("#ccc") {
        translate([pcb_x - 1.5, y_pi + 1.4, z_pb + 2]) cube([17.5, 16, 15]);
        translate([pcb_x - 1.5, y_pi + 1.4, z_pb + 20]) cube([17.5, 16, 15]);
        translate([pcb_x - 1.5, y_pi + 1.4, z_pb + 38]) cube([21, 13.5, 16]);
        translate([pcb_x + usbc_x - 4.5, y_pi + 1.4, z_pb - 1]) cube([9, 3.2, 7.5]);
    }
    color("#223a7a") translate([pcb_x + 21.5, y_pi + 12, z_top - 30]) cube([65, 1.6, 30]);
    color("#3a3") translate([pcb_x + 50, y_pi + 13.6, z_top - 30]) cube([15, 10, 8]);
    color("#222") {
        translate([wall + fit, spk_y0, wall + 0.4]) cube([spk_t, spk_w, spk_len - 2]);
        translate([W - wall - fit - spk_t, spk_y0, wall + 0.4]) cube([spk_t, spk_w, spk_len - 2]);
    }
    // Power plug and cable.
    color("#333") {
        translate([pcb_x + usbc_x - 6, y_pi - 0.5, z_pb - 24]) cube([12, 7, 23]);
        hull() {
            translate([pcb_x + usbc_x, y_pi + 3, z_pb - 26]) sphere(d = 4);
            translate([pcb_x + usbc_x, y_pi + 12, z_pb - 36]) sphere(d = 4);
        }
        hull() {
            translate([pcb_x + usbc_x, y_pi + 12, z_pb - 36]) sphere(d = 4);
            translate([pcb_x + usbc_x, D + 30, 7]) sphere(d = 4);
        }
    }
}

module trim() {
    for (x = knob_big_x) on_face(x, strip_z, 11) knob_big();
    for (x = knob_small_x) on_face(x, knob_small_z, 9) knob_small();
    for (x = bnc_x) on_face(x, strip_z, bnc_len + 1.4 - fit) bnc();
    handle_placed();
}

show_body = true;
show_back = true;
show_guts = true;
section_x = 0;         // cut the assembly open at this X to look inside
case_color = "#d9d2bf";
trim_color = "#2b2b2b";

module assembly() {
    // Stand it on its feet: rotate so the desk plane is level.
    rotate([-tilt, 0, 0]) translate([0, -foot_yf, foot_hf]) difference() {
        union() {
            if (show_body) color(case_color) body();
            if (show_back) color(case_color) back_panel();
            color(trim_color) trim();
            if (show_guts) electronics();
        }
        if (section_x > 0) translate([section_x, -500, -500]) cube(1000);
    }
}

// ---- Output ----------------------------------------------------------------------

if (part == "assembly") assembly();
else if (part == "body") rotate([90, 0, 0]) body();
else if (part == "fit_test") rotate([90, 0, 0]) fit_test();
else if (part == "back") translate([0, 0, D + bp_t]) rotate([-90, 0, 0]) back_panel();
else if (part == "handle") handle();
else if (part == "knob_big") knob_big();
else if (part == "knob_small") knob_small();
else if (part == "clip") clip();
else if (part == "bnc") bnc();
else if (part == "lock") translate([0, 0, -z_top - 0.1]) lock();
else assert(false, str("unknown part: ", part));
