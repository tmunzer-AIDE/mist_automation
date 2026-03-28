"""
Mist API service wrapper using the mistapi package.
Provides abstraction layer for all Mist API interactions.
"""

from typing import Any

import mistapi
import structlog
from mistapi import APISession
from mistapi.api.v1 import orgs as orgs_api
from mistapi.api.v1.orgs import sites, templates
from mistapi.api.v1.orgs import wlans as org_wlans
from mistapi.api.v1.sites import devices
from mistapi.api.v1.sites import sites as site_sites
from mistapi.api.v1.sites import wlans as site_wlans

from app.config import settings
from app.core.exceptions import ConfigurationError, MistAPIError

logger = structlog.get_logger(__name__)


class MistService:
    """Service for interacting with Mist API using mistapi package."""

    def __init__(
        self,
        api_token: str | None = None,
        org_id: str | None = None,
        cloud_region: str = "global",
    ):
        """
        Initialize Mist API service.

        Args:
            api_token: Mist API token (defaults to settings.mist_api_token)
            org_id: Mist Organization ID (defaults to settings.mist_org_id)
            cloud_region: Cloud region (global, eu, apac)
        """
        self.api_token = api_token or settings.mist_api_token
        self.org_id = org_id or settings.mist_org_id
        self.cloud_region = cloud_region

        if not self.api_token:
            raise ConfigurationError("Mist API token not configured")

        if not self.org_id:
            raise ConfigurationError("Mist Organization ID not configured")

        # Initialize API session
        self.session = self._create_session()

    def _create_session(self) -> APISession:
        """Create and configure Mist API session."""
        try:
            # Determine host based on cloud region
            host_map = {
                "global_01": "api.mist.com",
                "global_02": "api.gc1.mist.com",
                "global_03": "api.ac2.mist.com",
                "global_04": "api.gc2.mist.com",
                "global_05": "api.gc4.mist.com",
                "emea_01": "api.eu.mist.com",
                "emea_02": "api.gc3.mist.com",
                "emea_03": "api.ac6.mist.com",
                "emea_04": "api.gc6.mist.com",
                "apac_01": "api.ac5.mist.com",
                "apac_02": "api.gc5.mist.com",
                "apac_03": "api.gc7.mist.com",
            }
            host = host_map.get(self.cloud_region, "api.mist.com")

            # Create session
            session = APISession(
                host=host,
                apitoken=self.api_token,
                # max_retries=settings.mist_api_max_retries,
                # timeout=settings.mist_api_timeout,
            )

            logger.info("mist_api_session_created", org_id=self.org_id, cloud_region=self.cloud_region)
            return session

        except Exception as e:
            logger.error("mist_api_session_creation_failed", error=str(e))
            raise MistAPIError("Failed to create Mist API session") from e

    async def test_connection(self) -> tuple[bool, str | None]:
        """
        Test Mist API connection and credentials.

        Returns:
            tuple: (success, error_message)
        """
        try:
            # Try to get org details as a simple test
            result = await mistapi.arun(orgs_api.orgs.getOrg, self.session, self.org_id)

            if result.status_code == 200:
                logger.info("mist_api_connection_successful", org_id=self.org_id)
                return True, None
            else:
                error_msg = f"API returned status {result.status_code}"
                logger.warning("mist_api_connection_failed", error=error_msg)
                return False, error_msg

        except Exception as e:
            logger.error("mist_api_connection_error", error=str(e))
            return False, "Connection test failed"

    # ===== Organization Operations =====

    async def get_org_info(self) -> dict[str, Any]:
        """
        Get organization information.

        Returns:
            Organization data

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(orgs_api.orgs.getOrg, self.session, self.org_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get org info: {result.status_code}")

            logger.debug("org_info_retrieved", org_id=self.org_id)
            return result.data

        except Exception as e:
            logger.error("get_org_info_failed", error=str(e))
            raise MistAPIError("Mist API request failed") from e

    # ===== Site Operations =====

    async def get_sites(self) -> list[dict[str, Any]]:
        """
        Get all sites in the organization.

        Returns:
            List of site objects

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(sites.listOrgSites, self.session, self.org_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get sites: {result.status_code}")

            logger.debug("sites_retrieved", org_id=self.org_id, count=len(result.data))
            return result.data

        except Exception as e:
            logger.error("get_sites_failed", error=str(e))
            raise MistAPIError("Mist API request failed") from e

    async def get_site(self, site_id: str) -> dict[str, Any]:
        """
        Get site details.

        Args:
            site_id: Site UUID

        Returns:
            Site object

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(site_sites.getSiteInfo, self.session, site_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get site: {result.status_code}")

            logger.debug("site_retrieved", site_id=site_id)
            return result.data

        except Exception as e:
            logger.error("get_site_failed", site_id=site_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    # ===== WLAN Operations =====

    async def get_wlans(self, site_id: str | None = None) -> list[dict[str, Any]]:
        """
        Get WLANs (org-level or site-level).

        Args:
            site_id: Optional site ID for site-level WLANs

        Returns:
            List of WLAN objects

        Raises:
            MistAPIError: If API call fails
        """
        try:
            if site_id:
                # Get site WLANs
                result = await mistapi.arun(site_wlans.listSiteWlans, self.session, site_id)
            else:
                # Get org WLANs
                result = await mistapi.arun(org_wlans.listOrgWlans, self.session, self.org_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get WLANs: {result.status_code}")

            logger.debug("wlans_retrieved", site_id=site_id, count=len(result.data))
            return result.data

        except Exception as e:
            logger.error("get_wlans_failed", site_id=site_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    async def create_wlan(self, site_id: str, wlan_data: dict[str, Any]) -> dict[str, Any]:
        """
        Create a new WLAN.

        Args:
            site_id: Site UUID
            wlan_data: WLAN configuration

        Returns:
            Created WLAN object

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(site_wlans.createSiteWlan, self.session, site_id, wlan_data)

            if result.status_code not in (200, 201):
                raise MistAPIError(f"Failed to create WLAN: {result.status_code}")

            logger.info("wlan_created", site_id=site_id, wlan_id=result.data.get("id"))
            return result.data

        except Exception as e:
            logger.error("create_wlan_failed", site_id=site_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    async def update_wlan(self, site_id: str, wlan_id: str, wlan_data: dict[str, Any]) -> dict[str, Any]:
        """
        Update a WLAN.

        Args:
            site_id: Site UUID
            wlan_id: WLAN UUID
            wlan_data: Updated WLAN configuration

        Returns:
            Updated WLAN object

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(site_wlans.updateSiteWlan, self.session, site_id, wlan_id, wlan_data)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to update WLAN: {result.status_code}")

            logger.info("wlan_updated", site_id=site_id, wlan_id=wlan_id)
            return result.data

        except Exception as e:
            logger.error("update_wlan_failed", site_id=site_id, wlan_id=wlan_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    async def delete_wlan(self, site_id: str, wlan_id: str) -> None:
        """
        Delete a WLAN.

        Args:
            site_id: Site UUID
            wlan_id: WLAN UUID

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(site_wlans.deleteSiteWlan, self.session, site_id, wlan_id)

            if result.status_code not in (200, 204):
                raise MistAPIError(f"Failed to delete WLAN: {result.status_code}")

            logger.info("wlan_deleted", site_id=site_id, wlan_id=wlan_id)

        except Exception as e:
            logger.error("delete_wlan_failed", site_id=site_id, wlan_id=wlan_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    # ===== Template Operations =====

    async def get_templates(self) -> list[dict[str, Any]]:
        """
        Get all config templates in the organization.

        Returns:
            List of template objects

        Raises:
            MistAPIError: If API call fails
        """
        try:
            result = await mistapi.arun(templates.listOrgTemplates, self.session, self.org_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get templates: {result.status_code}")

            logger.debug("templates_retrieved", org_id=self.org_id, count=len(result.data))
            return result.data

        except Exception as e:
            logger.error("get_templates_failed", error=str(e))
            raise MistAPIError("Mist API request failed") from e

    # ===== Device Operations =====

    async def get_devices(self, site_id: str | None = None) -> list[dict[str, Any]]:
        """
        Get devices (org-level or site-level).

        Args:
            site_id: Optional site ID for site-level devices

        Returns:
            List of device objects

        Raises:
            MistAPIError: If API call fails
        """
        try:
            if site_id:
                # Get site devices
                result = await mistapi.arun(devices.listSiteDevices, self.session, site_id, type="all")
            else:
                # Get org devices
                result = await mistapi.arun(orgs_api.devices.listOrgDevices, self.session, self.org_id)

            if result.status_code != 200:
                raise MistAPIError(f"Failed to get devices: {result.status_code}")

            logger.debug("devices_retrieved", site_id=site_id, count=len(result.data))
            return result.data

        except Exception as e:
            logger.error("get_devices_failed", site_id=site_id, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    def get_session(self) -> APISession:
        """Return the underlying APISession for direct mistapi access (e.g., device_utils)."""
        return self.session

    # ===== Generic API Operations =====

    async def _api_call(
        self,
        method: str,
        endpoint: str,
        success_codes: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> Any:
        """Execute a Mist API call with common error handling."""
        endpoint = endpoint.replace("{org_id}", self.org_id)
        session_method = getattr(self.session, f"mist_{method}")

        try:
            result = await mistapi.arun(session_method, endpoint, **kwargs)

            if result.status_code not in success_codes:
                raise MistAPIError(
                    f"{method.upper()} {endpoint} failed: {result.status_code}",
                    api_status_code=result.status_code,
                )

            logger.info(f"api_{method}_success", endpoint=endpoint)
            return result.data

        except MistAPIError:
            raise
        except Exception as e:
            logger.error(f"api_{method}_failed", endpoint=endpoint, error=str(e))
            raise MistAPIError("Mist API request failed") from e

    async def api_get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generic GET request to Mist API."""
        return await self._api_call("get", endpoint, query=params or {})

    async def api_post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        """Generic POST request to Mist API."""
        return await self._api_call("post", endpoint, success_codes=(200, 201), body=data)

    async def api_put(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        """Generic PUT request to Mist API."""
        return await self._api_call("put", endpoint, body=data)

    async def api_delete(self, endpoint: str, params: dict[str, Any] | None = None) -> None:
        """Generic DELETE request to Mist API."""
        await self._api_call("delete", endpoint, success_codes=(200, 204), query=params or {})
