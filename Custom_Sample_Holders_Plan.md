# Implementation Plan: CustomSampleHolders Helper Class

## 1. Overview & Objective
The `CustomSampleHolders` class extends the machine fitting tools (`CircleFitter`, `RectangleFitter`) to allow alignment of known sample holder geometries. 

By measuring 3 physical points on a known sample holder in the machine coordinate system, the system calculates:
1. The 3D rotation matrix $R \in \mathrm{SO}(3)$ and translation vector $T \in \mathbb{R}^3$.
2. The full $4 \times 4$ homogeneous transformation matrix $M$ transforming local sample holder coordinates to machine coordinates.
3. The sample holder origin in machine coordinates ($T$).
4. The **Measured Workpiece Center**, factoring in user-specified additional offsets rotated by $R$:
   $$\mathbf{C}_{\text{workpiece}} = T + R \cdot \boldsymbol{\Delta}_{\text{offset}}$$
5. Machine movement to the calculated center and saving it to the `StoredPositions` list.

---

## 2. UI Mapping & Widgets
The UI layout is already configured in [Controller.ui](file:///d:/Projekte/Coding/Controller/GUI_files/Controller.ui) inside `fit_methods_tabWidget` (Tab 3: "Custom Sample Holders"):

| UI Element | Object Name | Purpose |
|---|---|---|
| Combo Box | `custom_holders_combobox` | Select active sample holder loaded from JSON |
| Point List | `custom_holders_listWidget` | Hosts 3 items of `fit_point_item.ui` |
| Offset Labels | `ch_additional_x_label`, `ch_additional_y_label`, `ch_additional_z_label` | Renamed according to JSON `"Additional_Offset_Labels"` |
| Offset Inputs | `ch_additional_x_spinbox`, `ch_additional_y_spinbox`, `ch_additional_z_spinbox` | User offsets ($\Delta X, \Delta Y, \Delta Z$) |
| Measured Center | `ch_measured_x_spinbox`, `ch_measured_y_spinbox`, `ch_measured_z_spinbox` | Displays calculated workpiece center in machine coordinates |
| Go To Button | `ch_go_to_button` | Moves machine to `ch_measured_*` position |
| Store Position Button | `ch_store_position_button` | Prompts user for a name and appends point to `StoredPositions` |

---

## 3. Data Schema: `settings/custom_sample_holders.json`
The configuration file is loaded via `PathManager.get_settings_path("custom_sample_holders.json")`:

```json
{
    "Rotary Stage": {
        "Point1": {
            "Name": "Top Left",
            "X": -10,
            "Y": 50,
            "Z": 20
        },
        "Point2": {
            "Name": "Top Right",
            "X": 10,
            "Y": 50,
            "Z": 20
        },
        "Point3": {
            "Name": "Bottom Right",
            "X": 0,
            "Y": -50,
            "Z": 20
        },
        "Additional_Offset_Labels": {
            "X": "X (mm)",
            "Y": "Half cylinder length (mm)",
            "Z": "Radius (mm)"
        }
    }
}
```

---

## 4. Mathematical Model (Arun's SVD / Kabsch Algorithm)

Given 3 reference points in the local sample holder frame:
$$\mathbf{P}_{\text{local}} = \{\mathbf{p}_1, \mathbf{p}_2, \mathbf{p}_3\} \subset \mathbb{R}^3$$
and 3 probed points in the machine frame:
$$\mathbf{P}_{\text{mach}} = \{\mathbf{q}_1, \mathbf{q}_2, \mathbf{q}_3\} \subset \mathbb{R}^3$$

### 4.1 Step-by-Step Solver
1. **Centroids**:
   $$\bar{\mathbf{p}} = \frac{1}{3} \sum_{i=1}^3 \mathbf{p}_i, \quad \bar{\mathbf{q}} = \frac{1}{3} \sum_{i=1}^3 \mathbf{q}_i$$
2. **Centered coordinates**:
   $$\tilde{\mathbf{p}}_i = \mathbf{p}_i - \bar{\mathbf{p}}, \quad \tilde{\mathbf{q}}_i = \mathbf{q}_i - \bar{\mathbf{q}}$$
3. **Cross-covariance matrix**:
   $$H = \sum_{i=1}^3 \tilde{\mathbf{p}}_i \tilde{\mathbf{q}}_i^T \in \mathbb{R}^{3 \times 3}$$
4. **Singular Value Decomposition (SVD)**:
   $$H = U \Sigma V^T$$
5. **Rotation Matrix**:
   $$R = V U^T$$
   *Reflection check*: If $\det(R) < 0$, multiply the 3rd column of $V$ by $-1$ and recalculate $R = V' U^T$.
6. **Translation Vector (Origin in Machine Frame)**:
   $$T = \bar{\mathbf{q}} - R \bar{\mathbf{p}}$$
   Since local origin is $(0,0,0)^T$:
   $$\mathbf{O}_{\text{mach}} = R \begin{bmatrix}0\\0\\0\end{bmatrix} + T = T$$
7. **Homogeneous Transformation Matrix (4x4)**:
   $$M = \begin{bmatrix} R & T \\ \mathbf{0}^T & 1 \end{bmatrix} \in \mathbb{R}^{4 \times 4}$$
8. **Workpiece Center with Rotated Offsets**:
   Given user offsets $\boldsymbol{\Delta}_{\text{offset}} = (\Delta X, \Delta Y, \Delta Z)^T$:
   $$\mathbf{C}_{\text{mach}} = T + R \cdot \boldsymbol{\Delta}_{\text{offset}}$$

---

## 5. Class Architecture: `CustomSampleHolders`

To be placed directly inside [Maschine_Helper.py](file:///d:/Projekte/Coding/Controller/Maschine_Helper.py) alongside `CircleFitter` and `RectangleFitter`.

### 5.1 Attributes
- `gui`: Reference to main GUI window.
- `controller`: Motion controller interface (`Artisan_Controller`).
- `stored_points`: Reference to `StoredPoints` instance.
- `file_path`: Path to `custom_sample_holders.json`.
- `holders_data`: Parsed JSON dictionary.
- `current_holder_name`: Name of active sample holder.
- `measured_points`: Dict mapping `"Point1"`, `"Point2"`, `"Point3"` to `Point` (or `None`).
- `reference_points`: Dict mapping `"Point1"`, `"Point2"`, `"Point3"` to `Point` (local coordinates).
- `rotation_matrix`: $3 \times 3$ NumPy array or `None`.
- `translation_vector`: $3 \times 1$ NumPy array or `None`.
- `transform_matrix`: $4 \times 4$ NumPy array or `None`.
- `measured_center`: Calculated `Point` (or `None`).

### 5.2 Core Methods
- `__init__(self, gui, controller, stored_points=None, file_path=None)`:
  - Cache UI widgets (with fallback attribute names for safety).
  - Connect combobox signals, offset spinbox change signals, and button signals.
  - Load JSON configuration and initialize UI.
- `load_holders_config()`:
  - Read JSON using `PathManager.get_settings_path("custom_sample_holders.json")`.
  - Populate `custom_holders_combobox`.
- `on_holder_selected(self, holder_name)`:
  - Update `current_holder_name`.
  - Update `Additional Offsets` labels (`ch_additional_x_label`, etc.) from `"Additional_Offset_Labels"`.
  - Reset offset spinboxes to 0.0.
  - Clear and recreate point items in `custom_holders_listWidget`.
  - Clear previous calculations and reset measured center spinboxes.
- `populate_point_list(self)`:
  - Instantiate 3 items using `fit_point_item.ui`.
  - Set label text to `Name` from JSON for Point1, Point2, Point3.
  - Hide/disable `remove_button` (same styling as `RectangleFitter`).
  - Connect `set_current_pos_button` -> `set_point_from_current_pos(key, widget)`.
  - Connect `move_to_button` -> `move_to_measured_point(key)`.
- `set_point_from_current_pos(self, key, widget)`:
  - Read `controller.get_absolute_position()`.
  - Update spinboxes on `widget`.
  - Store position in `measured_points[key]`.
  - Check if all 3 points are valid; if so, trigger `calculate_transformation()`.
- `calculate_transformation(self)`:
  - Run Arun's SVD solver.
  - Store `rotation_matrix`, `translation_vector`, and $4 \times 4$ `transform_matrix`.
  - Update `recalculate_workpiece_center()`.
- `recalculate_workpiece_center(self)`:
  - Read values from `ch_additional_x_spinbox`, `ch_additional_y_spinbox`, `ch_additional_z_spinbox`.
  - Compute $\mathbf{C}_{\text{mach}} = T + R \cdot \boldsymbol{\Delta}_{\text{offset}}$.
  - Update `ch_measured_x_spinbox`, `ch_measured_y_spinbox`, `ch_measured_z_spinbox`.
  - Enable `ch_go_to_button` and `ch_store_position_button`.
- `move_to_workpiece_center(self)`:
  - Call `controller.move_axis_absolute(C_x, C_y, C_z, speed=30)`.
- `store_workpiece_center(self)`:
  - Open `QInputDialog.getText` with default text = `self.current_holder_name`.
  - On confirm, call `self.stored_points.add_point(C_x, C_y, C_z, name=text)`.

---

## 6. Integration Steps in Existing Code

### 6.1 Update `MaschineHelpers` ([Maschine_Helper.py](file:///d:/Projekte/Coding/Controller/Maschine_Helper.py))
```python
def setup_helpers(self, circlefitter=True, rectanglefitter=True, storedpoints=True, customsampleholders=True, stored_points_file=None):
    if circlefitter:
        self.circle_fitter = CircleFitter(self.gui, self.controller)
    if rectanglefitter:
        self.rectangle_fitter = RectangleFitter(self.gui, self.controller)
    if storedpoints:
        self.stored_points = StoredPoints(self.gui, self.controller, file_path=stored_points_file)
    if customsampleholders:
        self.custom_sample_holders = CustomSampleHolders(
            self.gui, 
            self.controller, 
            stored_points=getattr(self, "stored_points", None)
        )
```

### 6.2 Spinbox Ranges & UI Polish
Ensure spinboxes handle standard machine ranges:
- Set `minimum = -10000.0`, `maximum = 10000.0`, `decimals = 3` for measured center and offset spinboxes.
- Initial state: `ch_go_to_button` and `ch_store_position_button` are disabled until all 3 points are set.

---

## 7. Edge Cases & Robustness
1. **Collinear or Duplicate Points**: Check that the 3 reference points and the 3 measured points do not have zero cross-product (singular/degenerate triangle). Log a warning and prevent invalid math if points are collinear.
2. **Widget Name Resiliency**: Handle slight variations in widget name if needed (`custom_holders_combobox` / `custom_holders_comobox`, `custom_holders_listWidget` / `custom_holder_listWidget`).
3. **Missing or Corrupted JSON**: If `custom_sample_holders.json` is missing or invalid, fail gracefully without crashing the UI, creating a default file or logging an error.
4. **Motion Speed / Controller Guard**: Validate that `controller.get_absolute_position()` is not `None` before recording points or issuing movements.

---

## 8. Verification & Test Plan
1. **Mathematical Unit Test**: Run an automated test verifying that known reference points with arbitrary 3D rotation and translation recover the exact transformation matrix and origin with zero numerical error.
2. **GUI Interaction Test**:
   - Verify sample holder names appear in `custom_holders_combobox`.
   - Verify changing holder updates point labels and offset labels.
   - Verify setting 3 points computes and populates the workpiece center.
   - Verify changing additional offsets immediately updates the workpiece center.
   - Verify Go To command sends target coordinates to the controller.
   - Verify Store Position opens name input dialog and adds the point to `StoredPositions`.
