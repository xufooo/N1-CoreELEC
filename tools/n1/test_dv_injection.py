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
    pos = text.index(name + "(")
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
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define DV_INJ_INTERVAL_MS 100
#define jiffies 0
#define msecs_to_jiffies(x) (x)
#define RGB_8BIT 0
#define EOTF_T_NULL 0
struct work_struct { int unused; };
struct kernel_param { void *arg; };
struct dv_info { unsigned ieeeoui; };
struct vout_device_s { struct dv_info *dv_info;
    int (*fresh_tx_vsif_pkt)(int,int,void*,bool); };
struct vinfo_s { struct vout_device_s *vout_device; };
static bool dv_injection_enable, dv_injection_active, dv_inj_ready;
static unsigned dm_metadata_size, dv_injection_path;
static bool always_send_vsif = true;
static int dv_injection_lock;
struct dv_inj_slot { bool valid; u8 num_pkts; u32 generation;
                     u32 pixel_data[5][1024]; };
static struct dv_inj_slot dv_inj_pool[64];
static struct dv_inj_slot dv_inj_static_slot;
#define VFRAME_SIGNAL_FMT_DOVI 4
#define EOTF_T_DOLBYVISION 1
#define DV_INJ_POOL_SIZE 64
struct vframe_s { unsigned index; struct { int fmt; } src_fmt; };
static unsigned int vdr_dm_data_source;
static u32 dv_inj_generation = 1;
struct dv_inj_runtime { bool ready; void *base; u32 page_bytes; u32 pages; };
static struct dv_inj_runtime dv_inj_rt;
static int resolve_result = 0, copy_result = 0;
static int released = 0;
static int dv_injection_resolve_canvas(const struct vinfo_s *v) { return resolve_result; }
static int dv_injection_copy_pixels(const struct dv_inj_slot *s) { return copy_result; }
static void dv_injection_release_output(void) { released++; dv_injection_active = false; }
static int video_on=1, canvas_result=0, send_result=0, off_packets=0, cancelled=0;
static struct dv_info sink={0x00d046};
static int tx_packet(int type,int mode,void *data,bool restore) {
    if (restore) { assert(!dv_injection_active); off_packets++; }
    return 0;
}
static struct vout_device_s device={&sink,tx_packet};
static struct vinfo_s video={&device};
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

MAIN = r'''
static void test_metadata(void) {
    u8 bad[594];
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
    dv_injection_enable=true; dv_injection_active=false;
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
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"metadata")) test_metadata();
    else if(!strcmp(argv[1],"layout")) test_layout();
    else if(!strcmp(argv[1],"lifecycle")) test_lifecycle();
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
                 "dv_injection_render_slot", "dv_injection_enable_set",
                 "dv_injection_block_hdr10", "dv_injection_render_frame")
        # Locate the definition, not the forward declaration.
        text = text.replace("static int dv_injection_enable_set(const char *val, const struct kernel_param *kp);", "")
        cfile = Path(cls.temp.name) / "contracts.c"
        capture = "static const u8 capture[] = {" + ",".join(map(str, CAPTURE)) + "};\n"
        cfile.write_text(PREFIX + capture + "\n".join(function(text,n) for n in names) + MAIN)
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


if __name__ == "__main__":
    unittest.main()
