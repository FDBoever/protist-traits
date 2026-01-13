import streamlit as st
import yaml
from pathlib import Path
from copy import deepcopy

# ==================================================
# Paths
# ==================================================
BASE = Path(".")
DATA = BASE / "data"
ONTOLOGY = BASE / "ontology"

DIRS = {
    "Taxon": DATA / "taxa",
    "Source": DATA / "sources",
    "Material": DATA / "materials",
    "Assertions": DATA / "assertions",
}

st.set_page_config(layout="wide", page_title="EukTrait Curator")

# ==================================================
# YAML utilities
# ==================================================
def load_yaml(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)

def list_yaml_ids(directory: Path):
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.yaml"))

def show_yaml(data):
    st.code(yaml.dump(data, sort_keys=False, allow_unicode=True), language="yaml")

def load_vocab(source):
    if isinstance(source, list):
        return source
    if isinstance(source, str):
        path = Path(source)
        if path.exists():
            return load_yaml(path)
    return []

# ==================================================
# Schema loaders
# ==================================================
@st.cache_data
def load_schema(schema_path: Path):
    return load_yaml(schema_path)

@st.cache_data
def load_traits(domain):
    return load_yaml(ONTOLOGY / domain / "traits.yaml")

@st.cache_data
def load_features(domain):
    return [f["feature_id"] for f in load_yaml(ONTOLOGY / domain / "features.yaml")]

@st.cache_data
def load_qualifiers():
    qdir = ONTOLOGY / "qualifiers"
    return {
        p.stem: load_yaml(p)
        for p in qdir.glob("*.yaml")
    }

QUALIFIERS = load_qualifiers()

# -----------------------------
# Generic field renderer (updated)
# -----------------------------

def normalize_spec(spec):
    """
    Allow shorthand schema definitions like:
      field: string
    by converting them to:
      field:
        value_type: string
    """
    if isinstance(spec, str):
        return {"value_type": spec}
    return spec

def render_field(name, spec, key_prefix):
    spec = normalize_spec(spec)
    key = f"{key_prefix}_{name}"

    # ----- Header block (tight spacing) -----
    title = name + (" *" if spec.get("required") else "")
    description = spec.get("description", "")

    st.markdown(
        f"""
        <div style="margin-bottom: 0.2rem;">
            <div style="font-weight: 600;">{title}</div>
            <div style="font-size: 0.9em; color: #555; margin-top: -2px;">
                {description}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    vtype = spec.get("value_type", "string")

    # ----- Primitive types -----
    if vtype == "string":
        return st.text_input("", key=key, label_visibility="collapsed")

    if vtype == "integer":
        return st.number_input("", step=1, key=key, label_visibility="collapsed")

    if vtype == "float":
        return st.number_input("", key=key, label_visibility="collapsed")

    # ----- Controlled vocabulary -----
    if vtype == "controlled_vocab":
        vocab = load_vocab(
            spec.get("vocabulary_source") or spec.get("vocabulary")
        )
        return st.selectbox("", vocab, key=key, label_visibility="collapsed")

    # ----- Reference -----
    if vtype == "reference":
        target = spec.get("target")
        if target in DIRS:
            options = ["— none —"] + list_yaml_ids(DIRS[target])
            return st.selectbox("", options, key=key, label_visibility="collapsed")
        return st.text_input("", key=key, label_visibility="collapsed")

    # ----- Object -----
    if vtype == "object":
        obj = {}
        for fname, fspec in spec.get("fields", {}).items():
            val = render_field(fname, fspec, key)
            if val not in ("", None):
                obj[fname] = val
        return obj or None

    # ----- List of objects -----
    if vtype == "list_of_objects":
        entries = st.session_state.setdefault(key, [])

        if st.button(f"+ Add {name}", key=f"{key}_add"):
            entries.append({})

        results = []
        for i in range(len(entries)):
            with st.container():
                st.markdown(
                    f"<div style='margin-top:0.5rem; font-weight:600;'>{name} #{i+1}</div>",
                    unsafe_allow_html=True
                )
                entry = {}
                for fname, fspec in spec.get("fields", {}).items():
                    val = render_field(fname, fspec, f"{key}_{i}")
                    if val not in ("", None):
                        entry[fname] = val
                if entry:
                    results.append(entry)

        return results or None

    return None


# -----------------------------
# Entity tabs
# -----------------------------
def entity_tab(entity_name, schema_path):
    st.header(entity_name)

    directory = DIRS[entity_name]
    schema = load_schema(schema_path)[entity_name]

    ids = list_yaml_ids(directory)
    col1, col2 = st.columns([1, 2])

    with col1:
        selected = st.selectbox(
            f"Select {entity_name}",
            ["— new —"] + ids,
            key=f"{entity_name}_select"
        )

    with col2:
        if selected != "— new —":
            show_yaml(load_yaml(directory / f"{selected}.yaml"))
            return

        st.subheader(f"Create new {entity_name}")
        payload = {}
        for field, spec in schema["fields"].items():
            val = render_field(field, spec, entity_name)
            if val not in ("", None):
                payload[field] = val

        if st.button(f"Save {entity_name}"):
            missing = [
                f for f, s in schema["fields"].items()
                if s.get("required") and f not in payload
            ]
            if missing:
                st.error(f"Missing required fields: {', '.join(missing)}")
                return

            file_id = payload.get(f"{entity_name.lower()}_id")
            if not file_id:
                st.error("Missing identifier field")
                return

            save_yaml(directory / f"{file_id}.yaml", payload)
            st.success(f"{entity_name} saved")

# -----------------------------
# Assertions tab (dropdowns for taxon/source)
# -----------------------------
def assertions_tab():
    st.header("Assertions")

    domain = st.selectbox(
        "Domain",
        sorted(p.name for p in DIRS["Assertions"].iterdir() if p.is_dir())
    )

    schema = load_schema(ONTOLOGY / "core" / f"{domain}_assertion_schema.yaml")
    traits = {t["trait_id"]: t for t in load_traits(domain)}
    features = load_features(domain)

    taxon_options = ["— none —"] + list_yaml_ids(DIRS["Taxon"])
    taxon_id = st.selectbox("taxon_id *", taxon_options)

    source_options = ["— none —"] + list_yaml_ids(DIRS["Source"])
    source_id = st.selectbox("source_id *", source_options)

    materials = list_yaml_ids(DIRS["Material"])
    material_id = st.selectbox("material_id (optional)", ["— none —"] + materials)

    feature = st.selectbox("feature *", features)
    trait_id = st.selectbox("trait *", list(traits))
    trait = traits[trait_id]

    # -----------------------------
    # Value
    # -----------------------------
    st.markdown("### Value")
    value_type = trait.get("value_type", "string")

    if value_type == "categorical":
        vocab = load_vocab(trait.get("vocabulary"))
        value = st.selectbox("", vocab)
    elif value_type == "integer":
        value = st.number_input("", step=1)
    elif value_type == "float":
        value = st.number_input("")
    else:
        value = st.text_input("")

    # -----------------------------
    # Qualifiers
    # -----------------------------
    qualifiers = {}
    with st.expander("Qualifiers"):
        for q, vocab in QUALIFIERS.items():
            sel = st.multiselect(q, vocab)
            if sel:
                qualifiers[q] = sel

    if st.button("Save assertion file"):
        if taxon_id == "— none —" or source_id == "— none —":
            st.error("taxon_id and source_id required")
            return

        aset = {
            "source_id": source_id,
            "assertions": [{
                "feature": feature,
                "trait": trait_id,
                "value": value,
                "qualifiers": qualifiers or None
            }]
        }
        if material_id != "— none —":
            aset["material_id"] = material_id

        payload = {"taxon_id": taxon_id, "assertion_sets": [aset]}
        save_yaml(DIRS["Assertions"] / domain / f"{taxon_id}.yaml", payload)
        st.success("Assertion file saved")

# ==================================================
# Sidebar navigation
# ==================================================
st.sidebar.title("EukTrait")
PAGE = st.sidebar.radio(
    "Navigate",
    ["Taxa", "Sources", "Materials", "Assertions"]
)

# ==================================================
# Router
# ==================================================
if PAGE == "Taxa":
    entity_tab("Taxon", ONTOLOGY / "core" / "taxonomy_assertion_schema.yaml")
elif PAGE == "Sources":
    entity_tab("Source", ONTOLOGY / "core" / "source_schema.yaml")
elif PAGE == "Materials":
    entity_tab("Material", ONTOLOGY / "core" / "material_schema.yaml")
else:
    assertions_tab()

