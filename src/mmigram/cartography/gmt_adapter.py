"""
Generic Mapping Tools (GMT) adapter for earthquake intensity surface generation.
Encapsulates existing GMT plot.sh scripting into a modular MapRendererInterface.
"""

import os
import shutil
import subprocess
from typing import List, Tuple, Optional
from .base import MapRendererInterface


SHAKEMAP_CPT = """
0    0 0 0 1    255 255 255
1    255 255 255 2    191 204 255
2    191 204 255 3    160 230 255
3    160 230 255 4    128 255 255
4    128 255 255 5    122 255 147
5    122 255 147 6    255 255 0
6    255 255 0   7    255 200 0
7    255 200 0   8    255 145 0
8    255 145 0   9    255 0   0
9    255 0   0   10   200 0   0
10   200 0   0   13   128 0   0
B    255 255 255
F    255 255 255
"""


class GMTMapRenderer(MapRendererInterface):
    """Renderer using Generic Mapping Tools (GMT)."""

    def __init__(self, assets_dir: str = "./assets"):
        self.assets_dir = assets_dir

    def is_available(self) -> bool:
        """Check whether GMT binary is on the system PATH."""
        return shutil.which("gmt") is not None

    def write_cpt(self, cpt_path: str) -> None:
        os.makedirs(os.path.dirname(cpt_path) or ".", exist_ok=True)
        with open(cpt_path, "w", encoding="utf-8") as f:
            f.write(SHAKEMAP_CPT.strip() + "\n")

    def generate_plot_script(
        self,
        script_path: str,
        records_path: str,
        output_png_path: str,
        bounds_str: str = "-R90/102/15/26",
        title: str = "Mandalay, Myanmar Earthquake Map",
    ) -> str:
        """Generate bash script invoking GMT blockmean and surface interpolation."""
        cpt_file = os.path.join(self.assets_dir, "shake.cpt")
        grid_file = os.path.join(self.assets_dir, "mmi_surface.nc")
        ps_file = output_png_path.replace(".png", ".ps")
        blockmean_file = os.path.join(self.assets_dir, "blockmean.txt")

        script_content = f"""#!/bin/bash
INPUT_FILE="{records_path}"
BLOCKMEAN_FILE="{blockmean_file}"
GRID_FILE="{grid_file}"
CPT_FILE="{cpt_file}"
PS_FILE="{ps_file}"
PNG_FILE="{output_png_path}"
BOUNDS="{bounds_str}"
PROJECTION="-JM8c"

if command -v gmt >/dev/null 2>&1; then
    gmt blockmean "$INPUT_FILE" $BOUNDS -I2m > "$BLOCKMEAN_FILE" 2>/dev/null || true
    if [ -s "$BLOCKMEAN_FILE" ]; then
        gmt surface "$BLOCKMEAN_FILE" -G"$GRID_FILE" -I2m $BOUNDS -T0.35 2>/dev/null || true
        gmt psbasemap $BOUNDS $PROJECTION -Bxa1f0.5 -Bya1f0.5 -B+t"{title}" -K > "$PS_FILE" 2>/dev/null || true
        gmt grdimage "$GRID_FILE" -C"$CPT_FILE" $BOUNDS $PROJECTION -O -K >> "$PS_FILE" 2>/dev/null || true
        gmt pscoast $BOUNDS $PROJECTION -Dh -W0.5p,black -Slightblue -Na/0.25p,gray -O -K >> "$PS_FILE" 2>/dev/null || true
        gmt psxy "$INPUT_FILE" $BOUNDS $PROJECTION -Sc0.45c -C"$CPT_FILE" -W0.25p,black -O -K >> "$PS_FILE" 2>/dev/null || true
        gmt psscale -C"$CPT_FILE" -Dx8c/-1.2c+w10c/0.5c+jTC+h -Bx2+l"MMI" -O >> "$PS_FILE" 2>/dev/null || true
        gmt psconvert "$PS_FILE" -A1.0c -Tg -P 2>/dev/null || true
        rm -f "$BLOCKMEAN_FILE" "$GRID_FILE" "$PS_FILE"
    fi
fi
"""
        os.makedirs(os.path.dirname(script_path) or ".", exist_ok=True)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        try:
            os.chmod(script_path, 0o755)
        except Exception:
            pass
        return script_path

    def render_shakemap(
        self,
        observation_points: List[Tuple[float, float, float]],
        output_file_path: str,
        title: str = "Earthquake Intensity Map",
        bounds: Optional[Tuple[float, float, float, float]] = None,
    ) -> str:
        """Write observation records and execute GMT script if available."""
        records_path = os.path.join(self.assets_dir, "records.txt")
        cpt_path = os.path.join(self.assets_dir, "shake.cpt")
        script_path = os.path.join(self.assets_dir, "plot.sh")

        self.write_cpt(cpt_path)

        os.makedirs(os.path.dirname(records_path) or ".", exist_ok=True)
        with open(records_path, "a", encoding="utf-8") as f:
            for lon, lat, mmi in observation_points:
                f.write(f"{lon} {lat} {mmi}\n")

        if bounds:
            min_lon, max_lon, min_lat, max_lat = bounds
            bounds_str = f"-R{min_lon}/{max_lon}/{min_lat}/{max_lat}"
        else:
            bounds_str = "-R90/102/15/26"

        self.generate_plot_script(
            script_path=script_path,
            records_path=records_path,
            output_png_path=output_file_path,
            bounds_str=bounds_str,
            title=title,
        )

        if self.is_available():
            subprocess.run(["bash", script_path], check=False)

        return output_file_path
