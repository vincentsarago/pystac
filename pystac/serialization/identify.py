from functools import total_ordering
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import pystac
from pystac.version import STACVersion
from pystac.extensions import Extensions


@total_ordering
class STACVersionID:
    """Defines STAC versions in an object that is orderable based on version number.
    For instance, ``1.0.0-beta.2 < 1.0.0``
    """
    def __init__(self, version_string: str) -> None:
        self.version_string = version_string

        # Account for RC or beta releases in version
        version_parts = version_string.split('-')
        self.version_core = version_parts[0]
        if len(version_parts) == 1:
            self.version_prerelease = None
        else:
            self.version_prerelease = '-'.join(version_parts[1:])

    def __str__(self) -> str:
        return self.version_string

    def __eq__(self, other: Any) -> bool:
        if type(other) is str:
            other = STACVersionID(other)
        return self.version_string == other.version_string

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other: Any) -> bool:
        if type(other) is str:
            other = STACVersionID(other)
        if self.version_core < other.version_core:
            return True
        elif self.version_core > other.version_core:
            return False
        else:
            return self.version_prerelease is not None and (
                other.version_prerelease is None
                or other.version_prerelease > self.version_prerelease)


class STACVersionRange:
    """Defines a range of STAC versions."""
    def __init__(self,
                 min_version: Union[str, STACVersionID] = '0.4.0',
                 max_version: Optional[Union[str, STACVersionID]] = None):
        if isinstance(min_version, str):
            self.min_version = STACVersionID(min_version)
        else:
            self.min_version = min_version

        if max_version is None:
            self.max_version = STACVersionID(STACVersion.DEFAULT_STAC_VERSION)
        else:
            if isinstance(max_version, str):
                self.max_version = STACVersionID(max_version)
            else:
                self.max_version = max_version

    def set_min(self, v: STACVersionID) -> None:
        if self.min_version < v:
            if v < self.max_version:
                self.min_version = v
            else:
                self.min_version = self.max_version

    def set_max(self, v: STACVersionID) -> None:
        if v < self.max_version:
            if self.min_version < v:
                self.max_version = v
            else:
                self.max_version = self.min_version

    def set_to_single(self, v: STACVersionID) -> None:
        self.set_min(v)
        self.set_max(v)

    def latest_valid_version(self) -> STACVersionID:
        return self.max_version

    def contains(self, v: Union[str, STACVersionID]) -> bool:
        if isinstance(v, str):
            v = STACVersionID(v)
        return self.min_version <= v and v <= self.max_version  # type:ignore

    def is_single_version(self) -> bool:
        return self.min_version >= self.max_version  # type:ignore

    def is_earlier_than(self, v: Union[str, STACVersionID]) -> bool:
        if isinstance(v, str):
            v = STACVersionID(v)
        return self.max_version < v

    def is_later_than(self, v: Union[str, STACVersionID]) -> bool:
        if isinstance(v, str):
            v = STACVersionID(v)
        return v < self.min_version

    def __repr__(self):
        return '<VERSIONS {}-{}>'.format(self.min_version, self.max_version)


class STACJSONDescription:
    """Describes the STAC object information for a STAC object represented in JSON

    Attributes:
        object_type (str): Describes the STAC object type. One of :class:`~pystac.STACObjectType`.
        version_range (STACVersionRange): The STAC version range that describes what
            has been identified as potential valid versions of the stac object.
        common_extensions (List[str]): List of common extension IDs implemented by this
            STAC object.
        custom_extensions (List[str]): List of custom extensions (URIs to JSON Schemas)
            used by this STAC Object.
    """
    def __init__(self, object_type: str, version_range: STACVersionRange,
                 common_extensions: List[str], custom_extensions: List[str]) -> None:
        self.object_type = object_type
        self.version_range = version_range
        self.common_extensions = common_extensions
        self.custom_extensions = custom_extensions

    def __repr__(self) -> str:
        return '<{} {} common_ext={} custom_ext={}>'.format(self.object_type, self.version_range,
                                                            ','.join(self.common_extensions),
                                                            ','.join(self.custom_extensions))


def _identify_stac_extensions(object_type: str, d: Dict[str, Any],
                              version_range: STACVersionRange) -> List[str]:
    """Identifies extensions for STAC Objects that don't list their
    extensions in a 'stac_extensions' property.

    Returns a list of stac_extensions. May mutate the version_range to update
    min or max version.
    """
    stac_extensions = set([])

    # assets (collection assets)

    if object_type == pystac.STACObjectType.ITEMCOLLECTION:
        if 'assets' in d:
            stac_extensions.add('assets')
            version_range.set_min(STACVersionID('0.8.0'))

    # checksum
    if 'links' in d:
        found_checksum = False
        for link in d['links']:
            # Account for old links as dicts
            if isinstance(link, str):
                link_props = cast(Dict[str, Any], d['links'][link]).keys()
            else:
                link_props = cast(Dict[str, Any], link).keys()

            if any(prop.startswith('checksum:') for prop in link_props):
                found_checksum = True
                stac_extensions.add(Extensions.CHECKSUM)
        if not found_checksum:
            if 'assets' in d:
                for asset in d['assets'].values():
                    asset_props = cast(Dict[str, Any], asset).keys()
                    if any(prop.startswith('checksum:') for prop in asset_props):
                        found_checksum = True
                        stac_extensions.add(Extensions.CHECKSUM)
        if found_checksum:
            version_range.set_min(STACVersionID('0.6.2'))

    # datacube
    if object_type == pystac.STACObjectType.ITEM:
        if any(k.startswith('cube:') for k in cast(Dict[str, Any], d['properties'])):
            stac_extensions.add(Extensions.DATACUBE)
            version_range.set_min(STACVersionID('0.6.1'))

    # datetime-range (old extension)
    if object_type == pystac.STACObjectType.ITEM:
        if 'dtr:start_datetime' in d['properties']:
            stac_extensions.add('datetime-range')
            version_range.set_min(STACVersionID('0.6.0'))

    # eo
    if object_type == pystac.STACObjectType.ITEM:
        if any(k.startswith('eo:') for k in cast(Dict[str, Any], d['properties'])):
            stac_extensions.add(Extensions.EO)
            if 'eo:epsg' in d['properties']:
                if d['properties']['eo:epsg'] is None:
                    version_range.set_min(STACVersionID('0.6.1'))
            if 'eo:crs' in d['properties']:
                version_range.set_max(STACVersionID('0.4.1'))
            if 'eo:constellation' in d['properties']:
                version_range.set_min(STACVersionID('0.6.0'))
        if 'eo:bands' in d:
            stac_extensions.add(Extensions.EO)
            version_range.set_max(STACVersionID('0.5.2'))

    # pointcloud
    if object_type == pystac.STACObjectType.ITEM:
        if any(k.startswith('pc:') for k in cast(Dict[str, Any], d['properties'])):
            stac_extensions.add(Extensions.POINTCLOUD)
            version_range.set_min(STACVersionID('0.6.2'))

    # sar
    if object_type == pystac.STACObjectType.ITEM:
        if any(k.startswith('sar:') for k in cast(Dict[str, Any], d['properties'])):
            stac_extensions.add(Extensions.SAR)
            version_range.set_min(STACVersionID('0.6.2'))
            if version_range.contains('0.6.2'):
                for prop in [
                        'sar:absolute_orbit', 'sar:resolution', 'sar:pixel_spacing', 'sar:looks'
                ]:
                    if prop in d['properties']:
                        if isinstance(d['properties'][prop], list):
                            version_range.set_max(STACVersionID('0.6.2'))
            if version_range.contains('0.7.0'):
                for prop in [
                        'sar:incidence_angle', 'sar:relative_orbit', 'sar:observation_direction',
                        'sar:resolution_range', 'sar:resolution_azimuth', 'sar:pixel_spacing_range',
                        'sar:pixel_spacing_azimuth', 'sar:looks_range', 'sar:looks_azimuth',
                        'sar:looks_equivalent_number'
                ]:
                    if prop in d['properties']:
                        version_range.set_min(STACVersionID('0.7.0'))
                if 'sar:absolute_orbit' in d['properties'] and not isinstance(
                        d['properties']['sar:absolute_orbit'], list):
                    version_range.set_min(STACVersionID('0.7.0'))
            if 'sar:off_nadir' in d['properties']:
                version_range.set_max(STACVersionID('0.6.2'))

    # scientific
    if object_type == pystac.STACObjectType.ITEM or object_type == pystac.STACObjectType.COLLECTION:
        if 'properties' in d:
            prop_keys = cast(Dict[str, Any], d['properties']).keys()
            if any(k.startswith('sci:') for k in prop_keys):
                stac_extensions.add(Extensions.SCIENTIFIC)
                version_range.set_min(STACVersionID('0.6.0'))

    # Single File STAC
    if object_type == pystac.STACObjectType.ITEMCOLLECTION:
        if 'collections' in d:
            stac_extensions.add(Extensions.SINGLE_FILE_STAC)
            version_range.set_min(STACVersionID('0.8.0'))
            if 'stac_extensions' not in d:
                version_range.set_max(STACVersionID('0.8.1'))

    return list(stac_extensions)


def _split_extensions(stac_extensions: List[str]) -> Tuple[List[str], List[str]]:
    """Split extensions into common_extensions and custom_extensions"""

    common_extensions: List[str] = []
    custom_extensions: List[str] = []
    for ext in stac_extensions:
        # Custom extensions are a URI
        if ext.endswith('.json') or '/' in ext:
            custom_extensions.append(ext)
        else:
            common_extensions.append(ext)

    return (common_extensions, custom_extensions)


def identify_stac_object_type(json_dict: Dict[str, Any]):
    """Determines the STACObjectType of the provided JSON dict.

    Args:
        json_dict (dict): The dict of STAC JSON to identify.

    Returns:
        STACObjectType: The object type represented by the JSON.
    """
    object_type = None

    # Identify pre-1.0 ITEMCOLLECTION (since removed)
    if 'type' in json_dict and 'assets' not in json_dict:
        if 'stac_version' in json_dict and cast(str, json_dict['stac_version']).startswith('0'):
            if json_dict['type'] == 'FeatureCollection':
                object_type = pystac.STACObjectType.ITEMCOLLECTION

    if 'extent' in json_dict:
        object_type = pystac.STACObjectType.COLLECTION
    elif 'assets' in json_dict:
        object_type = pystac.STACObjectType.ITEM
    else:
        object_type = pystac.STACObjectType.CATALOG

    return object_type


def identify_stac_object(json_dict: Dict[str, Any]) -> STACJSONDescription:
    """Determines the STACJSONDescription of the provided JSON dict.

    Args:
        json_dict (dict): The dict of STAC JSON to identify.

    Returns:
        STACJSONDescription: The description of the STAC object serialized in the
        given dict.
    """
    object_type = identify_stac_object_type(json_dict)

    version_range = STACVersionRange()

    stac_version = json_dict.get('stac_version')
    stac_extensions = json_dict.get('stac_extensions', None)

    if stac_version is None:
        if (object_type == pystac.STACObjectType.CATALOG
                or object_type == pystac.STACObjectType.COLLECTION):
            version_range.set_max(STACVersionID('0.5.2'))
        elif object_type == pystac.STACObjectType.ITEM:
            version_range.set_max(STACVersionID('0.7.0'))
        else:  # ItemCollection
            version_range.set_min(STACVersionID('0.8.0'))
    else:
        version_range.set_to_single(stac_version)

    if stac_extensions is not None:
        version_range.set_min(STACVersionID('0.8.0'))

    if stac_extensions is None:
        # If this is post-0.8, we can assume there are no extensions
        # if the stac_extensions property doesn't exist for everything
        # but ItemCollection (except after 0.9.0, when ItemCollection also got
        # the stac_extensions property).
        if version_range.is_earlier_than('0.8.0') or \
           (object_type == pystac.STACObjectType.ITEMCOLLECTION and not version_range.is_later_than(
               '0.8.1')):
            stac_extensions = _identify_stac_extensions(object_type, json_dict, version_range)
        else:
            stac_extensions = []

    if not version_range.is_single_version():
        # Final Checks

        if 'links' in json_dict:
            # links were a dictionary only in 0.5
            if 'links' in json_dict and isinstance(json_dict['links'], dict):
                version_range.set_to_single(STACVersionID('0.5.2'))

            # self links became non-required in 0.7.0
            if not version_range.is_earlier_than('0.7.0') and \
               not any(filter(lambda l: cast(Dict[str, Any], l)['rel'] == 'self',
                              json_dict['links'])):
                version_range.set_min(STACVersionID('0.7.0'))

    common_extensions, custom_extensions = _split_extensions(stac_extensions)
    return STACJSONDescription(object_type, version_range, common_extensions, custom_extensions)
