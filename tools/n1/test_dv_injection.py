#!/usr/bin/env python3
"""Compile extracted kernel pure functions and exercise their actual C bodies.

Host-only tests do not build a kernel, drive HDMI or prove playback quality.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from .test_hdmi_dm import CAPTURE
except ImportError:
    from test_hdmi_dm import CAPTURE

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "projects/Amlogic-ce/devices/Amlogic-ng/patches/linux/linux-20-tv-led-dolby-vision-injection.patch"


def source():
    text = PATCH.read_text().split("+++ b/drivers/amlogic/media/video_sink/dv_injection.c\n", 1)[1]
    return "\n".join(line[1:] for line in text.split("diff --git", 1)[0].splitlines()
                     if line.startswith("+"))


def function(text, name):
    # Skip forward declarations: take the occurrence that is a definition.
    pos = -1
    while True:
        pos = text.index(name + "(", pos + 1)
        line_start = text.rfind("\n", 0, pos) + 1
        prefix = text[line_start:pos].strip()
        in_comment = prefix.startswith(("/*", "*", "//"))
        semi = text.find(";", pos)
        brace = text.find("{", pos)
        if brace != -1 and (semi == -1 or brace < semi) and not in_comment:
            break
    start = text.rfind("\n", 0, pos) + 1
    opening = text.index("{", pos)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


PREFIX = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <assert.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
#define DV_INJ_MAX_METADATA_SIZE 594
#define DV_INJ_MAX_NUM_HDR_DM_PACKETS 5
#define DV_INJ_NUM_HDR_DM_PACKET_REPEATS 3
#define DV_INJ_PIXELS_PER_PKT 1024
#define DV_INJ_NUM_BYTES_PER_PACKET 128
#define DV_INJ_CRC_OFFSET 124
#define DV_INJ_BITS_PER_BYTE 8
#define DV_INJ_ODD_INJECTION 0xFFFFFFFF
#define DV_INJ_EVEN_INJECTION 0xFF000000
enum hdr_dm_packet_type { DV_INJ_FIRST_AND_ONLY_PKT = 0,
                          DV_INJ_FIRST_OF_MULTIPLE_PKT,
                          DV_INJ_CONTINUING_PKT,
                          DV_INJ_LAST_OF_MULTIPLE_PKT };
static unsigned int odd_pattern = DV_INJ_ODD_INJECTION;
static unsigned int even_pattern = DV_INJ_EVEN_INJECTION;
#define READ_ONCE(x) (x)
#define __iomem
#define WRITE_ONCE(x,v) ((x)=(v))
#define DV_INJ_INTERVAL_MS 100
#define jiffies 0
#define RGB_8BIT 0
#define EOTF_T_NULL 0
struct work_struct { int unused; };
struct kernel_param { void *arg; };
struct dv_info { unsigned ieeeoui; };
struct vout_device_s { struct dv_info *dv_info;
    int (*fresh_tx_vsif_pkt)(int,int,void*,bool); };
struct vinfo_s { struct vout_device_s *vout_device; int width; int height; };
static bool dv_injection_enable, dv_injection_active, dv_inj_ready;
static unsigned dm_metadata_size, dv_injection_path;
static bool always_send_vsif = true;
static int dv_injection_lock;
struct dv_inj_slot { bool valid; u8 num_pkts; u32 generation; u32 mode_gen;
                     u32 pixel_data[5][1024]; };
static struct dv_inj_slot dv_inj_pool[64];
static struct dv_inj_slot dv_inj_display_snapshot;
static int dv_inj_publish_lock;
#define spin_lock_irqsave(l, f) do { (void)(l); (f) = 0; } while (0)
#define spin_unlock_irqrestore(l, f) do { (void)(l); (void)(f); } while (0)
static struct dv_inj_slot dv_inj_static_slot;
#define VFRAME_SIGNAL_FMT_DOVI 4
#define EOTF_T_DOLBYVISION 1
#define DV_INJ_POOL_SIZE 64
struct vframe_s { unsigned index; struct { int fmt; } src_fmt; };
static unsigned int vdr_dm_data_source;
static bool force_block_other_vsif_for_DV, auto_block_other_vsif_for_DV = true;
static bool strict_dm_format = true;
struct delayed_work { int unused; };
static struct delayed_work dv_inj_watchdog;
static void schedule_delayed_work(struct delayed_work *w, unsigned long d) { (void)w; (void)d; }
static void cancel_delayed_work_sync(struct delayed_work *w) { (void)w; }
#define INIT_DELAYED_WORK(w, f) do { (void)(w); (void)(f); } while (0)
static bool dv_inj_stream_running;
static bool dv_inj_transport_requested;
static int dv_inj_render_busy;
static bool dv_inj_release_needed;
static void dv_inj_render_exit(void) { if (dv_inj_render_busy > 0) dv_inj_render_busy--; }
struct dv_inj_candidate { void *base; unsigned long long page_bytes; u32 pages; u32 gen; };
enum dv_inj_state { DV_INJ_IDLE = 0, DV_INJ_PREPARING, DV_INJ_READY, DV_INJ_CLOSING };
static int dv_inj_state;
static bool dv_inj_accepting;
static bool dv_inj_pending, dv_inj_pending_clear, dv_inj_pending_restore;
static u32 dv_inj_pending_gen;
static bool dv_inj_transport_ready;
static u32 dv_inj_mode_generation;
static void dv_injection_log(int level, const char *fmt, ...) { (void)level; (void)fmt; }

static unsigned long dv_injection_torn_frames;
static void dv_injection_output_seen_bad_frame(void) { dv_injection_torn_frames++; }

static u32 dv_inj_generation = 1;
struct dv_inj_runtime { bool ready; void *base; u32 page_bytes; u32 pages; };
static struct dv_inj_runtime dv_inj_rt;
static int resolve_result = 0, copy_result = 0;
static int released = 0;
static int dv_injection_copy_pixels(const struct dv_inj_slot *s) { return copy_result; }
static int video_on=1, canvas_result=0, send_result=0, off_packets=0, cancelled=0;
static struct dv_info sink={0x00d046};
static int tx_packet(int type,int mode,void *data,bool restore) {
    if (restore) { assert(!dv_injection_active); off_packets++; }
    return 0;
}
static struct vout_device_s device={&sink,tx_packet};

/* ---- hardware and scheduler stand-ins (real logic lives in the module) ---- */
static u32 dv_inj_buffer_generation;
static bool dv_inj_canvas_committed, dv_inj_canvas_dirty;
struct canvas_s { unsigned long addr; unsigned int width; unsigned int height; };
struct fb_fix_screeninfo_s { unsigned long smem_start; unsigned int smem_len; unsigned int line_length; };
struct fb_var_screeninfo_s { unsigned int xres, yres, yres_virtual, bits_per_pixel; };
struct fb_info {
	u8 *screen_base;
	struct fb_fix_screeninfo_s fix;
	struct fb_var_screeninfo_s var;
};
static struct fb_info fb0;
static struct fb_info *registered_fb[1] = { &fb0 };
static int lock_fb_info(struct fb_info *i) { (void)i; return 1; }
static void unlock_fb_info(struct fb_info *i) { (void)i; }
static void console_lock(void) {}
static void console_unlock(void) {}
static unsigned int osd_canvas = 0x40;
static unsigned int bytes_per_pixel = 4;
static unsigned int packet_repeat = 1;
static unsigned int osd_pixel_offset;
static void canvas_read(unsigned int idx, struct canvas_s *cs)
{
	(void)idx;
	cs->addr = fb0.fix.smem_start;
	cs->width = fb0.fix.line_length;
	cs->height = fb0.var.yres_virtual;
}
static int prepare_result = 0, transport_ok = 1, prepare_calls = 0;
/* Whether the injection still had its transport request set while the driver
 * was asked to prepare or restore the output.  The picture path itself must
 * never be reprogrammed, so the request has to be cleared for a restore.
 */
static int transport_requested_during_prepare = -1;
/* The driver may still notify while the output is being prepared (a mode
 * change or an HPD event can land inside the call).
 */
static int prepare_notifies = 0;
static void dv_injection_notify_output_lost(void);
static int hdmitx_prepare_output_for_injection(void)
{
	prepare_calls++;
	transport_requested_during_prepare = dv_inj_transport_requested ? 1 : 0;
	if (prepare_notifies)
		dv_injection_notify_output_lost();
	return prepare_result;
}
static bool hdmitx_transport_is_live(void) { return transport_ok; }
static unsigned long msecs_to_jiffies(unsigned long ms) { return ms; }
static void usleep_range(unsigned long a, unsigned long b) { (void)a; (void)b; }
static bool dv_inj_change_in_progress, dv_inj_in_prepare;
static bool dv_inj_user_wants, dv_inj_lost_during_prepare;
static u32 dv_inj_session;
static int deactivated_calls = 0;
static void dv_injection_deactivate(void);
static void dv_injection_release_output(void) { released++; dv_injection_active = false; }
static void dv_injection_begin_close(bool, bool);
static void dv_injection_begin_close_locked(bool, bool);

static struct vinfo_s video={&device,1920,1080};
static int dv_injection_build_candidate(const struct vinfo_s *vinfo, struct dv_inj_candidate *cand);
static int dv_injection_resolve_canvas(const struct vinfo_s *vinfo);

static u8 fb_storage[48 << 20];
static void fb_init(void)
{
	fb0.screen_base = fb_storage;
	fb0.fix.smem_start = 0x10000000UL;
	fb0.fix.smem_len = sizeof(fb_storage);
	fb0.fix.line_length = 7680;
	fb0.var.xres = 1920;
	fb0.var.yres = 1080;
	fb0.var.yres_virtual = 3240;
	fb0.var.bits_per_pixel = 32;
	video.width = 1920;
	video.height = 1080;
}

static const struct vinfo_s *get_current_vinfo(void) { return &video; }
static u32 get_video_enabled(void) { return video_on; }
static void mutex_lock(void *p) {}
static void mutex_unlock(void *p) {}
static void cancel_work_sync(void *p) { assert(!dv_injection_enable); cancelled++; }
static int param_set_bool(const char *s,const struct kernel_param *p) {
    if (!strcmp(s,"1") || !strcmp(s,"Y")) { *(bool *)p->arg=true; return 0; }
    if (!strcmp(s,"0") || !strcmp(s,"N")) { *(bool *)p->arg=false; return 0; }
    return -EINVAL;
}
static int dv_injection_write_canvas(const struct vinfo_s *v) { return canvas_result; }
static int dv_injection_send_vsif(const struct vinfo_s *v) { return send_result; }
'''

STUBS = r'''
static int dv_injection_build_candidate(const struct vinfo_s *vinfo, struct dv_inj_candidate *cand)
{
	(void)vinfo;
	memset(cand, 0, sizeof(*cand));
	cand->gen = dv_inj_buffer_generation;
	cand->page_bytes = 8294400;
	cand->pages = 3;
	return resolve_result;
}
static int dv_injection_resolve_canvas(const struct vinfo_s *vinfo)
{
	struct dv_inj_candidate c;
	if (dv_injection_build_candidate(vinfo, &c))
		return -EINVAL;
	return dv_injection_publish_candidate(&c);
}
'''

MAIN = r'''
/* The reference TV-led implementation ships this exact Display Management
 * payload as its static vdr_dm_data buffer (82 bytes: 70 byte fixed header,
 * one level 1 extension block of 6 bytes).  It must validate here, because
 * the packetiser hands the same bytes to the TV. */
static const u8 reference_dm[] = {
    0, 0, 32, 0, 3, 31, 6, 145, 32, 0, 252, 91, 4, 67, 32, 0,
    1, 11, 234, 87, 0, 0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0,
    66, 185, 254, 163, 254, 163, 254, 163, 66, 185, 254, 163, 254, 163, 254, 163,
    66, 185, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 12, 2, 1, 1,
    0, 62, 11, 134, 0, 42, 1, 0, 0, 0, 6, 1, 0, 62, 11, 134,
    2, 251,
};
static void test_metadata(void) {
    u8 bad[594];
    assert(dv_injection_validate_metadata(reference_dm,sizeof(reference_dm)) == 0);
    assert(dv_injection_validate_metadata(capture,sizeof(capture)) == 0);
    for (unsigned n=0;n<sizeof(capture);n++)
        assert(dv_injection_validate_metadata(capture,n) == -EINVAL);
    memcpy(bad,capture,sizeof(capture)); bad[74]=5; /* L1 wrong length */
    assert(dv_injection_validate_metadata(bad,sizeof(capture)) == -EINVAL);
    memcpy(bad,capture,sizeof(capture)); memset(bad+71,255,4);
    assert(dv_injection_validate_metadata(bad,sizeof(capture)) == -EINVAL);
    memcpy(bad,capture,sizeof(capture)); bad[60]=0;
    assert(dv_injection_validate_metadata(bad,sizeof(capture)) == -EINVAL);
    memcpy(bad,capture,sizeof(capture)); bad[70]++;
    assert(dv_injection_validate_metadata(bad,sizeof(capture)) == -EINVAL);
    memcpy(bad,capture,sizeof(capture)); bad[70]--;
    assert(dv_injection_validate_metadata(bad,sizeof(capture)) == -EINVAL);
    memset(bad,0,sizeof(bad)); bad[0]=0x19; bad[1]=8;
    assert(dv_injection_validate_metadata(bad,235) == -EINVAL);
    assert(dv_injection_validate_metadata(NULL,181) == -EINVAL);
}
static void test_layout(void) {
    u64 page; u32 pages;
    /* Recorded 7680-byte stride x3240 canvas = 3 real1080p pages. */
    assert(!dv_injection_canvas_layout(7680,1920,1080,3240,
        24883200,2,1,&page,&pages));
    assert(page==8294400 && pages==3);
    /* Old4K offset33177600bytes lies outside recorded allocation. */
    assert(page != 33177600 && page*pages <= 24883200);
    assert(dv_injection_canvas_layout(7680,3840,2160,3240,
        24883200,2,1,&page,&pages)==-EINVAL);
    for(unsigned r=0;r<=4;r++) {
        int ret=dv_injection_canvas_layout(15360,3840,2160,4320,
            66355200,5,r,&page,&pages);
        assert((ret==0)==(r>=1 && r<=3));
    }
    assert(dv_injection_canvas_layout(7680,1920,1080,3240,
        8294399,2,1,&page,&pages)==-EINVAL);
    assert(dv_injection_canvas_layout(7680,1920,1080,3241,
        24890880,2,1,&page,&pages)==-EINVAL);
    assert(dv_injection_canvas_layout(4,1,1,1,4,1,1,&page,&pages)==-EINVAL);
    assert(dv_injection_canvas_layout(0xfffffffcu,1,0xffffffffu,0xffffffffu,
        UINT64_MAX,1,1,&page,&pages)==-EINVAL);
}
static void reset(void) {
    fb_init();
    dv_inj_ready=true;
    dv_inj_state=DV_INJ_IDLE; dv_inj_pending=false; dv_inj_render_busy=0;
    dv_inj_change_in_progress=false; dv_inj_canvas_committed=false;
    dv_injection_enable=true; dv_injection_active=false;
    dv_inj_stream_running=true; dv_inj_transport_requested=true;
    dv_inj_transport_ready=true; dv_inj_mode_generation=0;
    dv_inj_accepting=true; dv_inj_state=DV_INJ_READY;
    dm_metadata_size=181; dv_injection_path=0;
    always_send_vsif=true; sink.ieeeoui=0x00d046;
    video_on=1; canvas_result=0; send_result=0;
}
static void test_lifecycle(void) {
    struct kernel_param kp={&dv_injection_enable};
    struct dv_inj_slot slot;
    struct vframe_s frame;

    memset(&frame,0,sizeof(frame));
    dv_inj_ready=false; dv_injection_enable=false;
    assert(dv_injection_enable_set("1",&kp)==-EAGAIN);
    dv_inj_ready=true;

    /* Enabling needs a resolvable canvas; failing must not enable. */
    resolve_result=-ENODEV;
    assert(dv_injection_enable_set("1",&kp)<0 && !dv_injection_enable);
    resolve_result=0;
    assert(!dv_injection_enable_set("1",&kp) && dv_injection_enable);

    memset(&slot,0,sizeof(slot));
    slot.valid=true; slot.num_pkts=2;
    slot.generation=dv_inj_generation;
    dv_inj_rt.ready=true;
    reset();
    dv_inj_rt.ready=true;

    /* Stale generation must not reach the sink. */
    slot.generation=dv_inj_generation-1;
    assert(!dv_injection_render_slot(&slot));
    slot.generation=dv_inj_generation;

    copy_result=-EINVAL;
    assert(!dv_injection_render_slot(&slot) && !dv_injection_block_hdr10());
    copy_result=0;
    reset(); dv_inj_rt.ready=true;
    sink.ieeeoui=0xdeadbe;
    assert(!dv_injection_render_slot(&slot));
    sink.ieeeoui=0x00d046;
    reset(); dv_inj_rt.ready=true;
    assert(dv_injection_render_slot(&slot));
    assert(dv_injection_block_hdr10());

    /* R6: no provider means no takeover, even with a valid slot. */
    reset(); dv_inj_rt.ready=true; dv_inj_stream_running=false;
    assert(!dv_injection_render_slot(&slot));
    dv_inj_stream_running=true;

    /* A non-DV frame at display time must hand the output back. */
    reset(); dv_inj_rt.ready=true;
    assert(dv_injection_render_slot(&slot));
    released=0;
    frame.src_fmt.fmt=0;
    assert(!dv_injection_render_frame(&frame));
    assert(released==1 && !dv_injection_block_hdr10());

    /* Disabling clears ownership and the resolved canvas. */
    reset(); dv_inj_rt.ready=true;
    assert(dv_injection_render_slot(&slot));
    assert(!dv_injection_enable_set("0",&kp));
    assert(!dv_injection_block_hdr10() && !dv_inj_rt.ready);
    assert(!dv_injection_render_slot(&slot));
}

static void test_state_machine(void) {
    struct kernel_param kp={0};
    kp.arg = &dv_injection_enable;   /* module_param binds the public bit */
    u32 t1,t2;

    /* Cold start: IDLE with no change history must reach READY. */
    reset();
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE;
    dv_inj_pending=false; dv_inj_accepting=false; dv_inj_transport_ready=false;
    dv_inj_rt.ready=false; dv_injection_active=false;
    resolve_result=0; prepare_result=0; transport_ok=1; prepare_calls=0;
    assert(!dv_injection_enable_set("1",&kp));
    assert(dv_injection_enable && dv_inj_state==DV_INJ_READY);
    assert(dv_inj_accepting && dv_inj_rt.ready && dv_inj_transport_ready);

    /* The driver may notify while the output is prepared (a mode change or an
     * HPD event can land inside the call).  The preparation must still
     * converge and publish - the notification only advances the generation.
     */
    reset();
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE;
    dv_inj_pending=false; dv_inj_accepting=false; dv_inj_transport_ready=false;
    dv_inj_rt.ready=false; dv_injection_active=false; dv_inj_user_wants=false;
    resolve_result=0; prepare_result=0; transport_ok=1; prepare_calls=0;
    prepare_notifies=1;
    assert(!dv_injection_enable_set("1",&kp));
    prepare_notifies=0;
    assert(dv_injection_enable && dv_inj_state==DV_INJ_READY);
    assert(dv_inj_accepting && dv_inj_rt.ready && dv_inj_transport_ready);

    /* A closing transaction owns the output: enabling during it is refused. */
    dv_injection_begin_close(true,true);
    assert(!dv_injection_enable && dv_inj_state==DV_INJ_CLOSING && dv_inj_pending);
    assert(dv_injection_enable_set("1",&kp)==-EAGAIN);
    assert(dv_inj_user_wants);   /* the request is remembered for later */

    /* No resume after this close: the user is not asking for injection. */
    dv_inj_user_wants=false;

    /* An in-flight commit defers the transaction. */
    dv_inj_render_busy=1;
    dv_inj_watchdog_fn(NULL);
    assert(dv_inj_pending && dv_inj_state==DV_INJ_CLOSING);
    dv_inj_render_busy=0;

    /* A failing physical restore keeps the transaction alive and retries. */
    prepare_result=-EIO;
    dv_inj_watchdog_fn(NULL);
    assert(dv_inj_pending && dv_inj_state==DV_INJ_CLOSING);
    assert(!dv_injection_enable);

    /* Once it succeeds the transaction ends. */
    prepare_result=0;
    dv_inj_watchdog_fn(NULL);
    assert(!dv_inj_pending && dv_inj_state==DV_INJ_IDLE);

    /* Completion tokens: only the current change may be committed. */
    t1 = dv_injection_note_canvas_change();
    t2 = dv_injection_note_canvas_change();
    assert(t2 == t1 + 1);
    assert(dv_injection_note_canvas_committed(t1) == -EAGAIN);
    assert(!dv_inj_canvas_committed);
    assert(!dv_injection_note_canvas_committed(t2));
    assert(dv_inj_canvas_committed && !dv_inj_change_in_progress);

    /* A canvas whose change has not completed must not be published. */
    {
        struct dv_inj_candidate c;
        (void)dv_injection_note_canvas_change();
        memset(&c,0,sizeof(c));
        c.gen = dv_inj_buffer_generation; c.page_bytes = 8294400; c.pages = 3;
        dv_inj_transport_requested=true;
        assert(dv_injection_publish_candidate(&c) == -EAGAIN);
        dv_inj_transport_requested=false;
    }


    /* A closing transaction must not request the injection transport: the
     * restore has to run with the request cleared. */
    {
        unsigned long f;
        dv_inj_state = DV_INJ_READY; dv_injection_enable = true;
        dv_inj_transport_requested = true; dv_injection_active = false;
        dv_injection_begin_close(true, true);
        assert(!dv_inj_transport_requested);
        assert(!dv_inj_transport_requested);
        (void)f;
    }

    /* Real stop -> close -> REG -> worker resume, without faking intent. */
    reset();
    kp.arg = &dv_injection_enable;
    prepare_result = 0; transport_ok = 1; resolve_result = 0;
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE; dv_inj_pending=false;
    dv_inj_user_wants=true;          /* the user enabled it once */
    assert(!dv_injection_enable_set("1",&kp));
    assert(dv_inj_state==DV_INJ_READY && dv_injection_enable);

    /* Provider stops: intent stays, public bit drops, close is scheduled. */
    dv_injection_new_stream();
    assert(!dv_inj_stream_running);
    assert(dv_inj_state==DV_INJ_CLOSING && dv_inj_pending);
    assert(!dv_injection_enable);
    assert(dv_inj_user_wants);       /* stop keeps the user intent */

    /* The close completes while the provider is gone: no resume. */
    prepare_result=0;
    dv_inj_watchdog_fn(NULL);
    assert(!dv_inj_pending && dv_inj_state==DV_INJ_IDLE);
    assert(dv_inj_user_wants && !dv_injection_enable);

    /* A new provider arrives while the close is still pending. */
    reset(); kp.arg=&dv_injection_enable;
    dv_injection_enable=false; dv_inj_state=DV_INJ_READY;
    dv_inj_transport_requested=true; dv_inj_user_wants=true;
    dv_injection_begin_close(true,true);
    dv_injection_stream_started();          /* REG during CLOSING */
    assert(dv_inj_stream_running);
    assert(dv_inj_state==DV_INJ_CLOSING);   /* the close still owns it */
    prepare_result=0; transport_ok=1;
    dv_inj_watchdog_fn(NULL);               /* finishes the close, then resumes */
    assert(!dv_inj_pending);
    /* One worker pass may finish the close and prepare in the same run. */
    assert(dv_inj_state==DV_INJ_PREPARING || dv_inj_state==DV_INJ_READY);
    if (dv_inj_state == DV_INJ_PREPARING)
        dv_inj_watchdog_fn(NULL);
    assert(dv_inj_state==DV_INJ_READY);
    assert(dv_injection_enable && dv_inj_transport_ready && dv_inj_accepting);


    /* A seek/reset keeps the provider registered and no REG follows: the
     * cache is dropped, the old frame is rejected, and preparation resumes on
     * its own because the user still wants injection and the stream is alive.
     */
    reset(); kp.arg = &dv_injection_enable;
    dv_injection_enable = true; dv_inj_state = DV_INJ_READY;
    dv_inj_stream_running = true; dv_inj_user_wants = true;
    dv_inj_transport_ready = true; dv_inj_accepting = true;
    dv_inj_rt.ready = true; dv_injection_active = true;
    dv_inj_pending = false; prepare_result = 0; transport_ok = 1; resolve_result = 0;
    {
        u32 gen_before = dv_inj_generation;
        struct dv_inj_slot old_frame;
        memset(&old_frame, 0, sizeof(old_frame));
        old_frame.valid = true; old_frame.generation = gen_before;
        old_frame.mode_gen = dv_inj_mode_generation;

        dv_injection_reset_stream();
        assert(dv_inj_generation != gen_before);   /* old frames invalidated */
        assert(dv_inj_stream_running);             /* reset is not a stop */
        dv_inj_watchdog_fn(NULL);                  /* close + resume, no REG */
        if (dv_inj_state == DV_INJ_PREPARING)
            dv_inj_watchdog_fn(NULL);
        assert(dv_inj_state == DV_INJ_READY);
        assert(dv_injection_enable && dv_inj_transport_ready && dv_inj_accepting);
        /* The frame captured before the reset must no longer be accepted. */
        assert(!dv_injection_render_slot(&old_frame));
    }

    /* A reset while the user does not want injection must not invent a
     * running provider or turn anything on. */
    reset();
    dv_injection_enable = false; dv_inj_state = DV_INJ_IDLE;
    dv_inj_stream_running = false; dv_inj_user_wants = false;
    dv_inj_pending = false; dv_inj_transport_ready = false;
    dv_injection_reset_stream();
    assert(!dv_inj_stream_running);
    assert(!dv_injection_enable && dv_inj_state == DV_INJ_IDLE);


    /* enable -> disable -> UNREG -> worker: the physical restore must survive
     * the later provider stop, and it must run with the request cleared.
     */
    reset(); kp.arg = &dv_injection_enable;
    prepare_result = 0; transport_ok = 1; resolve_result = 0;
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE; dv_inj_pending=false;
    dv_inj_user_wants=false; dv_inj_stream_running=true;
    assert(!dv_injection_enable_set("1",&kp));
    assert(dv_injection_enable && dv_inj_state==DV_INJ_READY);
    assert(!dv_injection_enable_set("0",&kp));       /* user disable */
    assert(dv_inj_pending && dv_inj_pending_restore);
    dv_injection_new_stream();                        /* UNREG while closing */
    assert(dv_inj_pending);
    assert(dv_inj_pending_restore);                   /* obligation merged, not dropped */
    prepare_calls = 0; transport_requested_during_prepare = -1;
    dv_inj_watchdog_fn(NULL);
    assert(prepare_calls >= 1);                       /* restore really ran */
    assert(transport_requested_during_prepare == 0);      /* without the transport request */
    assert(!dv_inj_pending && dv_inj_state==DV_INJ_IDLE);

    /* disable -> RESET -> worker behaves the same way. */
    reset(); kp.arg = &dv_injection_enable;
    prepare_result = 0; transport_ok = 1; resolve_result = 0;
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE; dv_inj_pending=false;
    dv_inj_user_wants=false; dv_inj_stream_running=true;
    assert(!dv_injection_enable_set("1",&kp));
    assert(!dv_injection_enable_set("0",&kp));
    assert(dv_inj_pending_restore);
    dv_injection_reset_stream();                      /* RESET while closing */
    assert(dv_inj_pending && dv_inj_pending_restore);
    prepare_calls = 0; transport_requested_during_prepare = -1;
    dv_inj_watchdog_fn(NULL);
    assert(prepare_calls >= 1);
    assert(transport_requested_during_prepare == 0);

    /* A failing restore keeps the obligation even if a stop arrives. */
    reset(); kp.arg = &dv_injection_enable;
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE; dv_inj_pending=false;
    dv_inj_user_wants=true; dv_inj_stream_running=true;
    prepare_result = 0; transport_ok = 1; resolve_result = 0;
    assert(!dv_injection_enable_set("1",&kp));
    assert(!dv_injection_enable_set("0",&kp));
    prepare_result = -EIO;
    dv_injection_new_stream();                        /* UNREG during failing close */
    dv_inj_watchdog_fn(NULL);
    assert(dv_inj_pending && dv_inj_pending_restore); /* still retrying */
    prepare_result = 0;
    dv_inj_watchdog_fn(NULL);
    assert(!dv_inj_pending);

    /* Provider state is tracked with injection off. */
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE;
    dv_inj_stream_running=false;
    dv_injection_stream_started();
    assert(dv_inj_stream_running);
    dv_injection_new_stream();
    assert(!dv_inj_stream_running);

    /* After a stop the user intent stays enabled, so a new provider
     * re-prepares instead of leaving injection dead. */
    /* State after a stop: the public bit is off but the user still wants it. */
    dv_injection_enable=false; dv_inj_state=DV_INJ_IDLE;
    dv_inj_user_wants=true;
    dv_inj_pending=false; prepare_result=0; transport_ok=1;
    dv_injection_stream_started();
    assert(dv_inj_state==DV_INJ_PREPARING);
    dv_inj_watchdog_fn(NULL);
    assert(dv_inj_state==DV_INJ_READY && dv_inj_transport_ready && dv_inj_accepting);
}

/* ------------------------------------------------------------------
 * Oracle: the TV-led reference implementation (the proven N1 scheme).
 * The functions below are a transcription of its packet builder:
 *   get_num_pkts() / get_hdr_dm_packet_type() / get_crc32() /
 *   set_hdr_dm_metadata_pkts()
 * The packet bytes produced by our module must match it exactly, because
 * the TV - not the box - parses these 128 byte packets.
 * ------------------------------------------------------------------ */
static u32 ref_crc_table[256];
static void ref_crc_init(void) {
    u32 i, j, c;
    for (i = 0; i < 256; i++) {
        c = i << 24;
        for (j = 0; j < 8; j++)
            c = (c & 0x80000000u) ? ((c << 1) ^ 0x04C11DB7u) : (c << 1);
        ref_crc_table[i] = c;
    }
}
static u32 ref_crc32(const u8 *data, u32 size) {
    u32 crc = 0xFFFFFFFF, i;
    for (i = 0; i < size; i++)
        crc = (crc << 8) ^ ref_crc_table[((crc >> 24) ^ data[i]) & 0xff];
    return crc;
}
static u32 ref_num_pkts(u32 len, u32 *last_pkt_len) {
    u32 num = 1;
    *last_pkt_len = len;
    if (*last_pkt_len > 119) {
        (*last_pkt_len) -= 119;
        while (*last_pkt_len > 121) { (*last_pkt_len) -= 121; num++; }
        if (*last_pkt_len > 0) num++;
    }
    return num;
}
static void ref_build_packets(const u8 *dm, u32 size,
                              u8 out[][DV_INJ_NUM_BYTES_PER_PACKET], u32 *num_pkts) {
    u32 last_pkt_len = 0, num = ref_num_pkts(size, &last_pkt_len);
    u32 bytes_written = 0, i;
    for (i = 0; i < num; i++) {
        u8 *cur = out[i];
        u32 cur_pkt_len, pkt_offset, crc;
        int type = (i == 0) ? ((num == 1) ? 0 : 1) : (((i + 1) != num) ? 2 : 3);
        memset(cur, 0, DV_INJ_NUM_BYTES_PER_PACKET);
        if (type == 0 || type == 1) {
            cur[0] = (type == 0) ? 0 : 0x40;
            cur[1] = dm[0];
            cur[2] = 0;
            cur[3] = (u8)(size >> 8);
            cur[4] = (u8)(size & 0xFF);
            cur_pkt_len = (type == 0) ? last_pkt_len : 119;
            pkt_offset = 5;
        } else {
            cur[0] = (type == 3) ? 0xC0 : 0x80;
            cur[1] = dm[0];
            cur[2] = 0;
            cur_pkt_len = (type == 3) ? last_pkt_len : 121;
            pkt_offset = 3;
        }
        memcpy(&cur[pkt_offset], &dm[bytes_written], cur_pkt_len);
        bytes_written += cur_pkt_len;
        if (bytes_written == size)
            memset(&cur[pkt_offset + cur_pkt_len], 0,
                   DV_INJ_NUM_BYTES_PER_PACKET - 4 - pkt_offset - cur_pkt_len);
        crc = ref_crc32(cur, DV_INJ_NUM_BYTES_PER_PACKET - 4);
        cur[DV_INJ_CRC_OFFSET] = (u8)(crc >> 24);
        cur[DV_INJ_CRC_OFFSET + 1] = (u8)(crc >> 16);
        cur[DV_INJ_CRC_OFFSET + 2] = (u8)(crc >> 8);
        cur[DV_INJ_CRC_OFFSET + 3] = (u8)crc;
    }
    *num_pkts = num;
}
static void ref_expand_pixels(const u8 byte_data[][DV_INJ_NUM_BYTES_PER_PACKET],
                              u32 num_pkts, u32 pixel_data[][DV_INJ_PIXELS_PER_PKT]) {
    u32 pkt, byte, bit;
    for (pkt = 0; pkt < num_pkts; pkt++)
        for (byte = 0; byte < DV_INJ_NUM_BYTES_PER_PACKET; byte++)
            for (bit = 0; bit < DV_INJ_BITS_PER_BYTE; bit++)
                pixel_data[pkt][byte * DV_INJ_BITS_PER_BYTE + bit] =
                    (((byte_data[pkt][byte]) >> (7 - bit)) & 1) ?
                        DV_INJ_ODD_INJECTION : DV_INJ_EVEN_INJECTION;
}
static void test_packets(void) {
    /* Sizes around the 119/121 byte payload boundaries of the format. */
    static const u32 sizes[] = {1, 70, 82, 118, 119, 120, 121, 240, 241, 362, 594};
    u8 dm[594];
    unsigned i, s;
    ref_crc_init();
    for (i = 0; i < sizeof(dm); i++)
        dm[i] = (u8)(0xA0 + i);
    for (s = 0; s < sizeof(sizes) / sizeof(sizes[0]); s++) {
        u32 size = sizes[s];
        u8 ours[DV_INJ_MAX_NUM_HDR_DM_PACKETS][DV_INJ_NUM_BYTES_PER_PACKET];
        u8 theirs[DV_INJ_MAX_NUM_HDR_DM_PACKETS][DV_INJ_NUM_BYTES_PER_PACKET];
        u32 our_pixels[DV_INJ_MAX_NUM_HDR_DM_PACKETS][DV_INJ_PIXELS_PER_PKT];
        u32 ref_pix[DV_INJ_MAX_NUM_HDR_DM_PACKETS][DV_INJ_PIXELS_PER_PKT];
        u8 our_num = 0;
        u32 ref_num = 0;
        memset(ours, 0xAA, sizeof(ours));
        memset(theirs, 0x55, sizeof(theirs));
        assert(dv_injection_pack_bytes(ours, &our_num, dm, size) == 0);
        ref_build_packets(dm, size, theirs, &ref_num);
        assert(our_num == ref_num);
        assert(memcmp(ours, theirs,
                      (size_t)our_num * DV_INJ_NUM_BYTES_PER_PACKET) == 0);
        memset(our_pixels, 0, sizeof(our_pixels));
        memset(ref_pix, 0, sizeof(ref_pix));
        dv_injection_expand_pixels(
            (const u8 (*)[DV_INJ_NUM_BYTES_PER_PACKET])ours, our_num, our_pixels);
        ref_expand_pixels(theirs, ref_num, ref_pix);
        assert(memcmp(our_pixels, ref_pix, sizeof(our_pixels)) == 0);
    }
    /* Out of range payloads are rejected, not silently truncated. */
    {
        u8 ours[DV_INJ_MAX_NUM_HDR_DM_PACKETS][DV_INJ_NUM_BYTES_PER_PACKET];
        u8 our_num = 0;
        assert(dv_injection_pack_bytes(ours, &our_num, dm, 0) == -EINVAL);
        assert(dv_injection_pack_bytes(ours, &our_num, dm, 595) == -EINVAL);
    }
}

int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"metadata")) test_metadata();
    else if(!strcmp(argv[1],"layout")) test_layout();
    else if(!strcmp(argv[1],"lifecycle")) test_lifecycle();
    else if(!strcmp(argv[1],"state")) test_state_machine();
    else if(!strcmp(argv[1],"packets")) test_packets();
    else return 2;
    return 0;
}
'''


class KernelInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if not compiler:
            raise unittest.SkipTest("host C compiler required")
        cls.temp = tempfile.TemporaryDirectory(prefix="n1-dv-kernel-")
        cls.binary = Path(cls.temp.name) / "contracts"
        text = source()
        names = ("dv_injection_block_length", "dv_injection_validate_metadata",
                 "dv_injection_canvas_layout", "dv_injection_deactivate",
                 "dv_injection_publish_candidate", "dv_injection_note_canvas_change",
                 "dv_injection_note_canvas_committed", "dv_injection_new_stream",
                 "dv_injection_stream_started", "dv_injection_reset_stream",
                 "dv_injection_begin_close", "dv_injection_begin_close_locked",
                 "dv_inj_prepare_locked", "dv_inj_watchdog_fn",
                 "dv_injection_render_slot", "dv_injection_enable_set",
                 "should_block_vsif", "dv_injection_block_hdr10",
                 "dv_injection_render_frame",
                 "dv_injection_notify_output_lost",
                 "dv_injection_crc32", "dv_injection_pkt_type",
                 "dv_injection_pack_bytes", "dv_injection_expand_pixels")
        # Locate the definition, not the forward declaration.
        text = text.replace("static int dv_injection_enable_set(const char *val, const struct kernel_param *kp);", "")
        cfile = Path(cls.temp.name) / "contracts.c"
        capture = "static const u8 capture[] = {" + ",".join(map(str, CAPTURE)) + "};\n"
        cfile.write_text(PREFIX + capture + "\n".join(function(text,n) for n in names) + STUBS + MAIN)
        subprocess.run([compiler,"-std=c99","-O1","-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer",str(cfile),"-o",str(cls.binary)],check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_public_dm_and_invalid_inputs(self):
        subprocess.run([str(self.binary),"metadata"],check=True)

    def test_recorded_canvas_bounds_and_parameters(self):
        subprocess.run([str(self.binary),"layout"],check=True)

    def test_activation_disable_and_boot_parameter_order(self):
        subprocess.run([str(self.binary),"lifecycle"],check=True)

    def test_state_machine(self):
        subprocess.run([str(self.binary),"state"],check=True)

    def test_packetizer_matches_reference(self):
        subprocess.run([str(self.binary),"packets"],check=True)


if __name__ == "__main__":
    unittest.main()
