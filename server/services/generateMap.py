import os
# Input: Mandalay earthquake MMI file
INPUT_DATA_FILE = "./assets/records.txt"
STATION_DATA_FILE = "./assets/stations.txt"
OUTPUT_PS_FILE = "./assets/mmi_mandalay_map.ps"
OUTPUT_PNG_FILE = "./assets/mmi_mandalay_map.png"
INTERPOLATE = "./assets/DYFI_city_points.txt"

GRID_FILE="./assets/mmi_surface.nc"
CPT_FILE="./assets/shake.cpt"
PNG_FILE="./assets/mmi_mandalay_map.png"
PS_FILE="./assets/mmi_mandalay_map.ps"

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

def generate_gmt_script():
    with open('./assets/shake.cpt', 'w') as f:
        f.write(SHAKEMAP_CPT)

    # Manually define bounds centered on Mandalay
    # center_lon, center_lat = 96.1, 21.95
    # lon_range = 5.0  # degrees left/right
    # lat_range = 6.0  # degrees up/down

    def get_bounds(filepath):
        lons, lats = [], []
        with open(filepath) as f:
            for line in f:
                try:
                    lon, lat, _ = map(float, line.strip().split())
                    lons.append(lon)
                    lats.append(lat)
                except:
                    continue
        return min(lons), max(lons), min(lats), max(lats)
    
    min_lon, max_lon, min_lat, max_lat = get_bounds(INTERPOLATE)
    bounds = f"-R{min_lon-0.5}/{max_lon+0.5}/{min_lat-0.5}/{max_lat+0.5}"

    # bounds = f"-R{min_lon}/{max_lon}/{min_lat}/{max_lat}"

    # unix style shell script
    with open('./assets/plot.sh', 'w') as f:
        f.write("#!/bin/bash\n\n")
        f.write(f"INPUT_FILE=\"{INPUT_DATA_FILE}\"\n")
        f.write(f"STATION_FILE=\"{STATION_DATA_FILE}\"\n")
        f.write("BLOCKMEAN_FILE=\"blockmean.txt\"\n")
        f.write(f"GRID_FILE=\"{GRID_FILE}\"\n")
        f.write(f"CPT_FILE=\"{CPT_FILE}\"\n")
        f.write(f"PS_FILE=\"{OUTPUT_PS_FILE}\"\n")
        f.write(f"PNG_FILE=\"{OUTPUT_PNG_FILE}\"\n")
        f.write(f"INTERPOLATE_FILE=\"{INTERPOLATE}\"\n")
        f.write(f"BOUNDS=\"{bounds}\"\n")
        f.write("PROJECTION=\"-JM8c\"\n\n")

        f.write("gmt blockmean \"$INTERPOLATE_FILE\" $BOUNDS -I2m > \"$BLOCKMEAN_FILE\"\n")
        f.write("gmt surface \"$BLOCKMEAN_FILE\" -G\"$GRID_FILE\" -I2m $BOUNDS -T0.35\n")
        f.write('gmt psbasemap $BOUNDS $PROJECTION -Bxa1f0.5 -Bya1f0.5 -B+t"Mandalay, Myanmar Earthquake Map" -K > $PS_FILE\n')
        f.write("gmt grdimage \"$GRID_FILE\" -C\"$CPT_FILE\" $BOUNDS $PROJECTION -O -K >> \"$PS_FILE\"\n")
        f.write("gmt pscoast $BOUNDS $PROJECTION -Dh -W0.5p,black -Slightblue -Na/0.25p,gray -O -K >> \"$PS_FILE\"\n")
        f.write("gmt psxy \"$INPUT_FILE\" $BOUNDS $PROJECTION -Sc0.45c -C\"$CPT_FILE\" -W0.25p,black -O -K >> \"$PS_FILE\"\n")
        f.write("gmt psxy \"$STATION_FILE\" $BOUNDS $PROJECTION -St0.6c -C\"$CPT_FILE\" -W0.5p,black -h1 -O -K >> \"$PS_FILE\"\n")
        f.write("gmt psscale -C\"$CPT_FILE\" -Dx8c/-1.2c+w10c/0.5c+jTC+h -Bx2+l\"MMI\" -O >> \"$PS_FILE\"\n")
        f.write("gmt psconvert \"$PS_FILE\" -A1.0c -Tg -P\n")
        f.write("rm -f \"$BLOCKMEAN_FILE\" \"$GRID_FILE\"\n")
        f.write("echo '✅ Done. PNG map saved as $PNG_FILE'\n")

    os.system("chmod +x plot.sh")

# if __name__ == '__main__':
#     generate_gmt_script()
#     print("Run: plot.sh")