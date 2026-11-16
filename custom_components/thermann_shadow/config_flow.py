"""Supported HA menus, selectors and inline help; unchanged stored options."""

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
import voluptuous as vol

from .config import (
    CLOUD_SOURCES,
    DEFAULT_SOURCES,
    OPTIONAL_SOURCES,
    DOMAIN,
    parse_options,
    rejection_message,
    saved_options,
)
from .configuration import (
    MENUS,
    PAGES,
    display_value,
    period_from_form,
    schedule_changes,
    schedule_rows,
    stored_changes,
    unit,
)
from .naming import ENTRY_TITLE
from .settings import CATALOG, apply_changes, locked_changes, locked_message


def sources_schema(values, keys=None):
    fields = {}
    for key in keys or (*DEFAULT_SOURCES, *OPTIONAL_SOURCES):
        # Suggested values allow optional mappings to be cleared, unlike defaults.
        marker = vol.Required if key in CLOUD_SOURCES else vol.Optional
        fields[marker(key, description={"suggested_value": values.get(key, "")})] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="water_heater" if key == "heater" else "sensor"
                )
            )
        )
    return vol.Schema(fields)


def options_schema(values, keys):
    fields = {}
    for key in keys:
        meta = CATALOG[key]
        if meta.kind == "switch":
            validator = selector.BooleanSelector()
        elif meta.kind == "form":
            validator = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        elif meta.kind == "text":
            validator = selector.TextSelector()
        elif meta.kind == "select":
            choices = list(meta.choices)
            if key.endswith("_c"):
                choices = [{"value": v, "label": f"{v}°C"} for v in choices]
            validator = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=choices,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key=key,
                )
            )
        elif meta.kind == "time":
            validator = selector.TimeSelector()
        else:
            config = {
                "min": display_value(key, meta.low),
                "max": display_value(key, meta.high),
                "step": 1
                if key in {"controller_max_commands_per_day", "controller_max_requests_per_day"}
                else "any",
                "mode": selector.NumberSelectorMode.BOX,
            }
            if unit(key):
                config["unit_of_measurement"] = unit(key)
            validator = selector.NumberSelector(config)
        if meta.kind == "text":
            fields[vol.Optional(key, description={"suggested_value": values[key]})] = validator
        else:
            fields[vol.Required(key, default=display_value(key, values[key]))] = validator
    return vol.Schema(fields)


def period_schema(row):
    return vol.Schema(
        {
            vol.Required(
                "days", default=[str(v) for v in row.get("days", range(7))]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(v) for v in range(7)],
                    multiple=True,
                    translation_key="days",
                )
            ),
            vol.Required("start", default=row.get("start", "00:00")): selector.TimeSelector(),
            vol.Required("end", default=row.get("end", "00:00")): selector.TimeSelector(),
            vol.Required("kind", default=row.get("kind", "off_peak")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["off_peak", "shoulder", "peak"],
                    translation_key="period_kind",
                )
            ),
            vol.Required(
                "months", default=[str(v) for v in row.get("months", range(1, 13))]
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[str(v) for v in range(1, 13)],
                    multiple=True,
                    translation_key="months",
                )
            ),
            vol.Required("use_rate", default="rate" in row): selector.BooleanSelector(),
            vol.Required(
                "rate", default=display_value("off_peak_rate", row.get("rate", 0))
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=200,
                    step="any",
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="c/kWh",
                )
            ),
        }
    )


class ShadowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 5  # Presentation-only; no storage schema migration.

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id("thermann_shadow_315l")
        self._abort_if_unique_id_configured()
        if user_input is not None:
            for entity in user_input.values():
                cv.entity_id(entity)
            from .installation import fresh_options

            return self.async_create_entry(
                title=ENTRY_TITLE,
                data=user_input,
                options=fresh_options(self.hass.config.time_zone),
            )
        return self.async_show_form(step_id="user", data_schema=sources_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ShadowOptionsFlow(config_entry)


class ShadowOptionsFlow(config_entries.OptionsFlow):
    """Small topical pages; every save keeps the full validation and lock guard."""

    def __init__(self, entry):
        self._entry = entry
        self._locked = ""
        self._rows = None
        self._row_index = None

    async def async_step_init(self, user_input=None):
        return self._menu("init")

    async def async_step_diagnostic_report(self, user_input=None):
        """Native copyable multiline view; closing never saves preferences."""
        from homeassistant.const import __version__
        from homeassistant.util import dt as dt_util
        from .report import build, text_report

        if user_input is not None:
            return self.async_abort(reason="report_closed")
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        report = (
            text_report(build(runtime, dt_util.utcnow(), __version__))
            if runtime
            else "Controller not loaded. Download diagnostics after resolving setup."
        )
        return self.async_show_form(
            step_id="diagnostic_report",
            data_schema=vol.Schema(
                {
                    vol.Required("report", default=report): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=True)
                    )
                }
            ),
        )

    def _menu(self, step_id):
        return self.async_show_menu(step_id=step_id, menu_options=list(MENUS[step_id]))

    async def async_step_electricity(self, user_input=None):
        return self._menu("electricity")

    async def async_step_solar_meters(self, user_input=None):
        return self._menu("solar_meters")

    async def async_step_advanced(self, user_input=None):
        return self._menu("advanced")

    def _current_sources(self):
        return dict(self._entry.options.get("sources", self._entry.data))

    def _finish(self, before, result, step_id, schema, facts=None):
        from .settings_entity import control_active

        locked = locked_changes(before, result)
        if locked and control_active(self.hass, self._entry):
            self._locked = locked_message(locked)
            placeholders = {**(facts or {}), "detail": self._locked}
            if step_id == "schedule":
                from .configuration_text import schedule_summary

                placeholders["periods"] = schedule_summary(self._rows, before)
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                errors={"base": "locked_while_active"},
                description_placeholders=placeholders,
            )
        return self.async_create_entry(title="", data=result)

    async def async_step_sources(self, user_input=None):
        return await self._sources_page(
            "sources",
            user_input,
            tuple(k for k in (*DEFAULT_SOURCES, *OPTIONAL_SOURCES) if k not in CLOUD_SOURCES),
        )

    async def async_step_bridge_sources(self, user_input=None):
        return await self._sources_page(
            "bridge_sources", user_input, tuple(k for k in DEFAULT_SOURCES if k in CLOUD_SOURCES)
        )

    async def _sources_page(self, step_id, user_input, keys):
        values = self._current_sources()
        if user_input is not None:
            for entity in user_input.values():
                cv.entity_id(entity)
            # Omitted optional fields mean deliberately unmapped. Keep the
            # other page's mappings (and unknown keys) exactly as stored.
            updated = {
                k: v
                for k, v in values.items()
                if k not in keys or (v == "" and k not in user_input)
            } | user_input
            before = {**saved_options(self._entry.options), "sources": values}
            result = {**saved_options(self._entry.options), "sources": updated}
            if updated.get("heater_power") != values.get("heater_power"):
                result["heater_meter_verification"] = ""
                result["learning_hardware_qualified"] = False
            return self._finish(before, result, step_id, sources_schema(updated, keys))
        return self.async_show_form(step_id=step_id, data_schema=sources_schema(values, keys))

    async def async_step_hot_water(self, user_input=None):
        return await self._settings_page("hot_water", user_input)

    async def async_step_heating_preferences(self, user_input=None):
        return await self._settings_page("heating_preferences", user_input)

    async def async_step_ct_free_setup(self, user_input=None):
        """Real-meter sanity and experimental owner choice; no heater commands."""
        from homeassistant.util import dt as dt_util
        from .solar import ct_free_record, grid_sanity

        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        now = dt_util.utcnow()
        values = saved_options(self._entry.options)
        grid = runtime._reading("grid") if runtime else None
        source = self._current_sources().get("grid", "unmapped")
        live_kw = runtime._kw("grid", now) if runtime else None
        direction = (user_input or {}).get(
            "direction", "import_positive" if values["import_positive"] else "export_positive"
        )
        signed = (
            (live_kw if direction == "import_positive" else -live_kw)
            if live_kw is not None
            else None
        )
        quality = grid_sanity(
            signed,
            runtime._kw("pv_ac", now) if runtime else None,
            runtime._kw("house", now) if runtime else None,
            values["pv_ac_limit_kw"],
        )
        record = ct_free_record(
            source,
            grid.unit if grid else None,
            direction == "import_positive",
            values["element_kw"],
        )
        identity = (source, grid.unit if grid else None, values["element_kw"])
        if user_input is None:
            self._ct_free_identity = identity
        facts = {
            "source": source,
            "unit": str(grid.unit if grid else "unknown"),
            "quality": quality.replace("_", " "),
        }
        errors = {}
        data = user_input or {
            "direction": direction,
            "confirm_direction": False,
            "accept_experimental": False,
            "enable_boost": values["optional_solar_boost"],
            "allow_peak": values["peak_heating_policy"] == "Verified solar-only heating",
        }
        schema = vol.Schema(
            {
                vol.Required("direction", default=data["direction"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["import_positive", "export_positive"],
                        translation_key="grid_direction",
                    )
                ),
                **{
                    vol.Required(k, default=data[k]): selector.BooleanSelector()
                    for k in (
                        "confirm_direction",
                        "accept_experimental",
                        "enable_boost",
                        "allow_peak",
                    )
                },
            }
        )
        if user_input is not None:
            if identity != getattr(self, "_ct_free_identity", None):
                errors["base"] = "meter_changed_reopen"
            elif not user_input["confirm_direction"] or not user_input["accept_experimental"]:
                errors["base"] = "experimental_ack_required"
            elif (
                not record
                or quality != "consistent_measured_site_power"
                or self._current_sources().get("heater_power")
                or values["heater_meter_verification"]
            ):
                errors["base"] = "meter_not_ready"
            else:
                changes = {
                    "ct_free_solar_verification": record,
                    "import_positive": direction == "import_positive",
                    "meter_verified": True,
                    "optional_solar_boost": user_input["enable_boost"],
                    "peak_heating_policy": "Verified solar-only heating"
                    if user_input["allow_peak"]
                    else "Never schedule heating during peak",
                }
                result = apply_changes(values, changes)
                parse_options(result)
                before = {**values, "sources": self._current_sources()}
                return self._finish(
                    before,
                    {**result, "sources": self._current_sources()},
                    "ct_free_setup",
                    schema,
                    facts,
                )
        return self.async_show_form(
            step_id="ct_free_setup",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "source": source,
                "unit": str(grid.unit if grid else "unknown"),
                "quality": quality.replace("_", " "),
                "detail": self._locked,
            },
        )

    async def async_step_prices(self, user_input=None):
        return await self._settings_page("prices", user_input)

    async def async_step_peak_times(self, user_input=None):
        return await self._settings_page("peak_times", user_input)

    async def async_step_tariff_json(self, user_input=None):
        return await self._settings_page("tariff_json", user_input)

    async def async_step_solar(self, user_input=None):
        return await self._settings_page("solar", user_input)

    async def async_step_equipment(self, user_input=None):
        return await self._settings_page("equipment", user_input)

    async def async_step_polling(self, user_input=None):
        return await self._settings_page("polling", user_input)

    async def async_step_commissioning(self, user_input=None):
        return await self._settings_page("commissioning", user_input)

    async def _settings_page(self, step_id, user_input):
        values = saved_options(self._entry.options)
        errors = {}
        if user_input is not None:
            before = {**values, "sources": self._current_sources()}
            user_input = {
                **{k: "" for k in PAGES[step_id] if CATALOG[k].kind == "text"},
                **user_input,
            }
            values = apply_changes(values, stored_changes(values, user_input))
            try:
                parse_options(values)
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                errors["base"] = "invalid_settings"
                self._locked = rejection_message(error)
            else:
                return self._finish(
                    before,
                    {**values, "sources": self._current_sources()},
                    step_id,
                    options_schema(values, PAGES[step_id]),
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=options_schema(values, PAGES[step_id]),
            errors=errors,
            description_placeholders={"detail": self._locked},
        )

    def _schedule_schema(self):
        from .configuration_text import DAYS, KINDS

        fields = {
            vol.Required("action", default="edit"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["edit", "add", "delete", "save"],
                    translation_key="schedule_action",
                )
            ),
        }
        if self._rows:
            fields[vol.Optional("period")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        {
                            "value": str(i),
                            "label": f"{i + 1}. {', '.join(DAYS[d][:3] for d in r['days'])}: {r['start']}–{r['end']} — {KINDS[r['kind']]}",
                        }
                        for i, r in enumerate(self._rows)
                    ]
                )
            )
        return vol.Schema(fields)

    async def async_step_schedule(self, user_input=None):
        values = saved_options(self._entry.options)
        if self._rows is None:
            self._rows = schedule_rows(values["tariff_periods"])
        errors = {}
        if user_input is not None:
            action = user_input["action"]
            index = int(user_input.get("period", -1))
            if action == "save":
                try:
                    changes = schedule_changes(values, self._rows)
                except (ValueError, TypeError, KeyError, OverflowError) as error:
                    errors["base"] = "invalid_settings"
                    self._locked = rejection_message(error)
                else:
                    before = {**values, "sources": self._current_sources()}
                    return self._finish(
                        before,
                        {**apply_changes(values, changes), "sources": self._current_sources()},
                        "schedule",
                        self._schedule_schema(),
                    )
            elif action == "add" and len(self._rows) < 32:
                self._row_index = None
                return await self.async_step_period()
            elif action in {"edit", "delete"} and 0 <= index < len(self._rows):
                self._row_index = index
                if action == "delete":
                    return await self.async_step_delete_period()
                return await self.async_step_period()
            else:
                errors["base"] = "choose_period"
        from .configuration_text import schedule_summary

        return self.async_show_form(
            step_id="schedule",
            data_schema=self._schedule_schema(),
            errors=errors,
            description_placeholders={
                "detail": self._locked,
                "periods": schedule_summary(self._rows, values),
            },
        )

    async def async_step_period(self, user_input=None):
        original = self._rows[self._row_index] if self._row_index is not None else {}
        errors = {}
        if user_input is not None:
            try:
                row = period_from_form(user_input, original)
            except (ValueError, TypeError, KeyError, OverflowError):
                errors["base"] = "invalid_period"
            else:
                self._locked = ""
                if self._row_index is None:
                    self._rows.append(row)
                else:
                    self._rows[self._row_index] = row
                return await self.async_step_schedule()
        return self.async_show_form(
            step_id="period",
            data_schema=period_schema(original),
            errors=errors,
        )

    async def async_step_delete_period(self, user_input=None):
        if user_input is not None:
            if user_input["confirm"]:
                self._rows.pop(self._row_index)
            return await self.async_step_schedule()
        return self.async_show_form(
            step_id="delete_period",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
        )
