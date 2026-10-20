"""empty message

Revision ID: aa684b60e683
Revises: 5003b9acb1f4
Create Date: 2026-10-17 21:30:32.448254

"""
import copy
import gzip
import json
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'aa684b60e683'
down_revision = '5003b9acb1f4'
branch_labels = None
depends_on = None

OLD_VERSION = '0.12'
NEW_VERSION = '0.13'

HEAVY_ION_ID = 25
HEAVY_ION_NAME = 'Heavy ions'

# (old id, PDG code, name, A, Z) for SHIELD-HIT12A, FLUKA and Common projects
COMMON_PARTICLES = [
    (1, 2112, 'Neutron', 1, 0),
    (2, 2212, 'Proton', 1, 1),
    (3, -211, 'Pion π-', None, None),
    (4, 211, 'Pion π+', None, None),
    (7, -2212, 'Anti-proton', 1, 1),
    (8, -321, 'Kaon κ-', None, None),
    (9, 321, 'Kaon κ+', None, None),
    (10, 311, 'Kaon κ0', None, None),
    (11, 130, 'Kaon κ~', None, None),
    (15, 13, 'Muon µ-', None, None),
    (16, -13, 'Muon µ+', None, None),
    (21, 1000010020, 'Deuteron', 2, 1),
    (22, 1000010030, 'Triton', 3, 1),
    (23, 1000020030, 'Helium-3', 3, 2),
    (24, 1000020040, 'Helium-4', 4, 2),
    # electron was available only for FLUKA, its id does not collide with other ids
    (26, 11, 'Electron', None, None),
]

# (old id, PDG code, name, A, Z) for Geant4 projects, ids have different meaning than in COMMON_PARTICLES
GEANT4_PARTICLES = [
    (1, 2112, 'Neutron', 1, 0),
    (2, 2212, 'Proton', 1, 1),
    (3, 22, 'Photon', None, None),
    (4, 11, 'Electron', None, None),
    (5, -11, 'Positron', None, None),
    (6, 1000020040, 'Alpha', 4, 2),
    (7, 13, 'Muon µ-', None, None),
    (8, -13, 'Muon µ+', None, None),
    (9, -211, 'Pion π-', None, None),
    (10, 211, 'Pion π+', None, None),
    (11, 1000060120, '12C', 12, 6),
]


def _particle_table(simulator: str) -> list:
    return GEANT4_PARTICLES if simulator == 'geant4' else COMMON_PARTICLES


def heavy_ion_pdg(a: int, z: int) -> int:
    """PDG code of a nucleus: 10LZZZAAAI with L = 0 and I = 0"""
    return 1000000000 + z * 10000 + a * 10


def old_particle_to_pdg(particle: dict, simulator: str) -> int:
    """Converts particle object from editor JSON 0.12 to PDG code"""
    particle_id = particle['id']
    if particle_id == HEAVY_ION_ID:
        return heavy_ion_pdg(a=int(particle['a']), z=int(particle['z']))
    for old_id, pdg, *_ in _particle_table(simulator):
        if old_id == particle_id:
            return pdg
    raise ValueError(f'Unknown particle id {particle_id} for simulator {simulator}')


def pdg_to_old_particle(pdg: int, simulator: str, with_az: bool = True) -> dict:
    """Converts PDG code to particle object from editor JSON 0.12"""
    for old_id, table_pdg, name, a, z in _particle_table(simulator):
        if table_pdg == pdg:
            particle = {'id': old_id, 'name': name}
            if with_az and a is not None:
                particle.update(a=a, z=z)
            return particle
    if pdg >= 1000000000:
        return {'id': HEAVY_ION_ID, 'name': HEAVY_ION_NAME, 'a': pdg % 10000 // 10, 'z': pdg // 10000 % 1000}
    raise ValueError(f'PDG code {pdg} has no equivalent in editor JSON {OLD_VERSION} for simulator {simulator}')


def _set_versions(editor_json: dict, version: str) -> None:
    """Sets version in the top level metadata and in metadata of all managers"""
    editor_json['metadata']['version'] = version
    for value in editor_json.values():
        if isinstance(value, dict) and isinstance(value.get('metadata'), dict) and 'version' in value['metadata']:
            value['metadata']['version'] = version


def _filters(editor_json: dict) -> list:
    return (editor_json.get('scoringManager') or {}).get('filters') or []


def upgrade_editor_json(editor_json: dict, simulator: str) -> dict:
    """Returns a copy of editor JSON 0.12 converted to 0.13"""
    result = copy.deepcopy(editor_json)
    beam = result.get('beam')
    if beam and 'particle' in beam:
        beam['particle_PDG'] = old_particle_to_pdg(beam.pop('particle'), simulator)
    for scoring_filter in _filters(result):
        if isinstance(scoring_filter.get('particle'), dict):
            scoring_filter['particle_PDG'] = old_particle_to_pdg(scoring_filter.pop('particle'), simulator)
        data = scoring_filter.get('data')
        if isinstance(data, dict) and 'particleTypes' in data:
            data['particle_PDGs'] = [old_particle_to_pdg(p, simulator) for p in data.pop('particleTypes')]
    _set_versions(result, NEW_VERSION)
    return result


def downgrade_editor_json(editor_json: dict, simulator: str) -> dict:
    """Returns a copy of editor JSON 0.13 converted to 0.12"""
    result = copy.deepcopy(editor_json)
    beam = result.get('beam')
    if beam and 'particle_PDG' in beam:
        beam['particle'] = pdg_to_old_particle(beam.pop('particle_PDG'), simulator)
    for scoring_filter in _filters(result):
        if 'particle_PDG' in scoring_filter:
            scoring_filter['particle'] = pdg_to_old_particle(scoring_filter.pop('particle_PDG'),
                                                             simulator,
                                                             with_az=False)
        data = scoring_filter.get('data')
        if isinstance(data, dict) and 'particle_PDGs' in data:
            data['particleTypes'] = [pdg_to_old_particle(pdg, simulator) for pdg in data.pop('particle_PDGs')]
    _set_versions(result, OLD_VERSION)
    return result


def _migrate_inputs(from_version: str, migrate_fn) -> None:
    """Applies migrate_fn to editor JSON of all simulation inputs with version equal to from_version"""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text('SELECT i.id, i.compressed_data, s.sim_type FROM "Input" i '
                'JOIN "Simulation" s ON s.id = i.simulation_id')).fetchall()

    for input_id, compressed_data, sim_type in rows:
        if compressed_data is None:
            continue
        data = json.loads(gzip.decompress(compressed_data).decode('utf-8'))
        editor_json = data.get('input_json') if isinstance(data, dict) else None
        if not isinstance(editor_json, dict) or (editor_json.get('metadata') or {}).get('version') != from_version:
            continue

        simulator = (editor_json.get('project') or {}).get('simulator') or sim_type
        try:
            data['input_json'] = migrate_fn(editor_json, simulator)
        except (KeyError, TypeError, ValueError) as e:
            logging.warning('Failed to migrate editor JSON of input %d: %s', input_id, e)
            continue

        connection.execute(sa.text('UPDATE "Input" SET compressed_data = :data WHERE id = :id'), {
            'data': gzip.compress(json.dumps(data).encode('utf-8')),
            'id': input_id
        })


def upgrade():
    _migrate_inputs(OLD_VERSION, upgrade_editor_json)


def downgrade():
    _migrate_inputs(NEW_VERSION, downgrade_editor_json)

