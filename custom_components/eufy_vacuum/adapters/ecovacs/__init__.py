"""Ecovacs Deebot adapter package.

Wraps the Home Assistant **core** ``ecovacs`` integration (``deebot-client``), the same
way ``adapters/roborock`` wraps core ``roborock``. Two public surfaces:

- ``adapter.register_ecovacs_adapter_for_vacuum`` — the entry point core CALLS.
- ``const.UPSTREAM_PLATFORMS`` — the identity core READS (``("ecovacs",)``).

What the upstream integration gives us, and therefore what this adapter can and cannot do
(read from ``homeassistant/components/ecovacs`` — see ``vocabulary.py`` for the wire words):

- Rooms are a ``rooms`` ATTRIBUTE on the vacuum entity, ``{slugified_name: id | [ids]}``
  for the ACTIVE map only -> ``discovery.room_list_shape = "name_id_mapping"``.
- A room clean is ``vacuum.send_command`` with ``spot_area`` and
  ``{rooms: [ids], cleanings: n}`` -> the shared ``generic_room_ids`` engine.
- Suction, water and work mode are DEVICE-GLOBAL (no per-room wire), so they ride
  ``dispatch.global_pre_calls``; per-room passes collapse to one batch scalar.
- There is no lifecycle sensor: the VACUUM entity's own state is the lifecycle signal.
- There is no live pose / current-room entity, so run segmentation is declared off and
  external-run room attribution is declared noop (omission would silently run another
  brand's engine).
"""
