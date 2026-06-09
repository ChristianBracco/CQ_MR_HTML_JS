from dicom_loader import load_dicom_series
from roi_tools import calculate_geometric_accuracy
slices = load_dicom_series(r'D:\MRI CQ HTML JS\DICOM\0000840D\AAE1B9CE\AAB20682', recursive=True)
r = calculate_geometric_accuracy(slices[4].pixel_array, slices[4].pixel_spacing_mm)
gd = r.get('grid_distortion')
dots = r.get('grid_dots', [])
print(f"dots={len(dots)}")
if gd:
    print(f"H={gd['n_horizontal_lines']} V={gd['n_vertical_lines']} spacing={gd['median_spacing_mm']:.1f}mm std={gd['spacing_std_mm']:.2f}")
