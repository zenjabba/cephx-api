"""CephX authentication management endpoints."""

import json
import logging
import re
from typing import Union, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.ceph import CephAuthAlreadyExists, CephAuthNotFound, CephClient, CephCommandError
from app.core.auth import AuthContext, verify_api_key
from app.core.logging import audit_logger
from app.models.auth import (
    APIResponse,
    CephXAuthEntity,
    CephXAuthList,
    CreateAuthRequest,
    UpdateCapsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="",
    tags=["Authentication"],
    dependencies=[Depends(verify_api_key)],
)


async def require_auth_read(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    """Dependency that requires auth:read permission."""
    auth.require_permission("auth:read")
    return auth


async def require_auth_write(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    """Dependency that requires auth:write permission."""
    auth.require_permission("auth:write")
    return auth


def get_ceph_client() -> CephClient:
    """Dependency to get CephClient instance.

    Returns:
        CephClient instance
    """
    return CephClient()


@router.post(
    "/auth",
    status_code=status.HTTP_201_CREATED,
    response_model=APIResponse,
    summary="Create CephX Authentication",
    description="Create a new CephX authentication entity with specified capabilities",
)
async def create_auth(
    request: CreateAuthRequest,
    auth: Annotated[AuthContext, Depends(require_auth_write)],
    ceph: Annotated[CephClient, Depends(get_ceph_client)],
) -> APIResponse:
    """Create a new CephX authentication entity.

    Args:
        request: Creation request with client name and capabilities
        auth: Authenticated user context
        ceph: CephClient instance

    Returns:
        APIResponse with created auth details

    Raises:
        HTTPException: If creation fails or client already exists
    """
    # Validate at least one capability is specified
    try:
        request.validate_capabilities()
    except ValueError as e:
        audit_logger.log_operation(
            operation="CREATE",
            resource=f"auth:client.{request.client_name}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APIResponse.error(
                code="INVALID_CAPABILITIES",
                message=str(e),
            ).model_dump(exclude_none=True),
        )

    entity = f"client.{request.client_name}"
    caps_dict = request.capabilities.to_dict()

    try:
        # First check if entity already exists
        exists = await check_auth_exists_internal(ceph, entity)
        if exists:
            audit_logger.log_operation(
                operation="CREATE",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Entity already exists"},
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=APIResponse.error(
                    code="AUTH_ALREADY_EXISTS",
                    message=f"Authentication entity already exists: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        # Build command for get-or-create
        cmd = ["auth", "get-or-create", entity]
        for subsystem, cap_value in caps_dict.items():
            cmd.extend([subsystem, cap_value])
        cmd.extend(["--format", "json"])

        # Execute command
        result = await ceph.execute(cmd, format_json=True)

        # Parse result
        if isinstance(result, list) and len(result) > 0:
            auth_data = result[0]
        elif isinstance(result, dict):
            auth_data = result
        else:
            raise CephCommandError(
                "Unexpected response format from Ceph",
                error_code="INVALID_RESPONSE",
            )

        # Create response entity
        auth_entity = CephXAuthEntity(
            entity=auth_data.get("entity", entity),
            key=auth_data.get("key", ""),
            caps=auth_data.get("caps", {}),
        )

        audit_logger.log_operation(
            operation="CREATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="SUCCESS",
            details={"capabilities": caps_dict},
        )

        return APIResponse.success(data=auth_entity.model_dump())

    except CephCommandError as e:
        audit_logger.log_operation(
            operation="CREATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e), "error_code": e.error_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=APIResponse.error(
                code=e.error_code,
                message=e.message,
                details=e.details,
            ).model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.exception(f"Unexpected error creating auth: {e}")
        audit_logger.log_operation(
            operation="CREATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=APIResponse.error(
                code="INTERNAL_ERROR",
                message="Internal server error",
                details={"error": str(e)},
            ).model_dump(exclude_none=True),
        )


@router.get(
    "/auth/{client_name}",
    response_model=APIResponse,
    summary="Get CephX Authentication",
    description="Get authentication details for a specific client",
)
async def get_auth(
    client_name: str,
    auth: Annotated[AuthContext, Depends(require_auth_read)],
    ceph: Annotated[CephClient, Depends(get_ceph_client)],
) -> APIResponse:
    """Get authentication details for a client.

    Args:
        client_name: Client name (with or without 'client.' prefix)
        auth: Authenticated user context
        ceph: CephClient instance

    Returns:
        APIResponse with auth details

    Raises:
        HTTPException: If client not found
    """
    # Normalize entity name
    entity = client_name if client_name.startswith("client.") else f"client.{client_name}"

    try:
        # Execute get command
        result = await ceph.execute(["auth", "get", entity, "--format", "json"], format_json=True)

        # Parse result
        if isinstance(result, list) and len(result) > 0:
            auth_data = result[0]
        elif isinstance(result, dict):
            auth_data = result
        else:
            raise CephAuthNotFound(entity)

        # Create response entity
        auth_entity = CephXAuthEntity(
            entity=auth_data.get("entity", entity),
            key=auth_data.get("key", ""),
            caps=auth_data.get("caps", {}),
        )

        audit_logger.log_operation(
            operation="READ",
            resource=f"auth:{entity}",
            user=auth.user,
            status="SUCCESS",
        )

        return APIResponse.success(data=auth_entity.model_dump())

    except CephAuthNotFound:
        audit_logger.log_operation(
            operation="READ",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": "Not found"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=APIResponse.error(
                code="AUTH_NOT_FOUND",
                message=f"Authentication entity not found: {entity}",
                details={"entity": entity},
            ).model_dump(exclude_none=True),
        )
    except CephCommandError as e:
        # Check if error indicates not found
        if e.status_code == 404 or "not found" in e.message.lower():
            audit_logger.log_operation(
                operation="READ",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Not found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=APIResponse.error(
                    code="AUTH_NOT_FOUND",
                    message=f"Authentication entity not found: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        audit_logger.log_operation(
            operation="READ",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e), "error_code": e.error_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=APIResponse.error(
                code=e.error_code,
                message=e.message,
                details=e.details,
            ).model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.exception(f"Unexpected error getting auth: {e}")
        audit_logger.log_operation(
            operation="READ",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=APIResponse.error(
                code="INTERNAL_ERROR",
                message="Internal server error",
                details={"error": str(e)},
            ).model_dump(exclude_none=True),
        )


@router.put(
    "/auth/{client_name}/caps",
    response_model=APIResponse,
    summary="Update CephX Capabilities",
    description="Update capabilities for an existing client (empty capabilities suspends the client)",
)
async def update_caps(
    client_name: str,
    request: UpdateCapsRequest,
    auth: Annotated[AuthContext, Depends(require_auth_write)],
    ceph: Annotated[CephClient, Depends(get_ceph_client)],
) -> APIResponse:
    """Update capabilities for a client.

    Args:
        client_name: Client name (with or without 'client.' prefix)
        request: Update request with new capabilities
        user: Authenticated user info
        ceph: CephClient instance

    Returns:
        APIResponse with updated capabilities

    Raises:
        HTTPException: If client not found or update fails
    """
    # Normalize entity name
    entity = client_name if client_name.startswith("client.") else f"client.{client_name}"

    try:
        # First check if entity exists
        exists = await check_auth_exists_internal(ceph, entity)
        if not exists:
            audit_logger.log_operation(
                operation="UPDATE",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Not found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=APIResponse.error(
                    code="AUTH_NOT_FOUND",
                    message=f"Authentication entity not found: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        # Build command for caps update
        caps_dict = request.capabilities.to_dict()
        cmd = ["auth", "caps", entity]

        # If empty capabilities, this suspends the client (removes all caps)
        if caps_dict:
            for subsystem, cap_value in caps_dict.items():
                cmd.extend([subsystem, cap_value])
        else:
            # To suspend, we still need to provide empty caps for all subsystems
            # Just call with entity only, or provide empty strings
            cmd.extend(["mon", "", "osd", "", "mds", "", "mgr", ""])

        # Execute command
        await ceph.execute(cmd)

        # Get updated auth to return
        result = await ceph.execute(["auth", "get", entity, "--format", "json"], format_json=True)

        if isinstance(result, list) and len(result) > 0:
            auth_data = result[0]
        elif isinstance(result, dict):
            auth_data = result
        else:
            auth_data = {"entity": entity, "caps": caps_dict}

        audit_logger.log_operation(
            operation="UPDATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="SUCCESS",
            details={"capabilities": caps_dict},
        )

        return APIResponse.success(
            data={
                "entity": entity,
                "caps": auth_data.get("caps", caps_dict),
            }
        )

    except CephCommandError as e:
        # Check if error indicates not found
        if e.status_code == 404 or "not found" in e.message.lower():
            audit_logger.log_operation(
                operation="UPDATE",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Not found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=APIResponse.error(
                    code="AUTH_NOT_FOUND",
                    message=f"Authentication entity not found: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        audit_logger.log_operation(
            operation="UPDATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e), "error_code": e.error_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=APIResponse.error(
                code=e.error_code,
                message=e.message,
                details=e.details,
            ).model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.exception(f"Unexpected error updating caps: {e}")
        audit_logger.log_operation(
            operation="UPDATE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=APIResponse.error(
                code="INTERNAL_ERROR",
                message="Internal server error",
                details={"error": str(e)},
            ).model_dump(exclude_none=True),
        )


@router.delete(
    "/auth/{client_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete CephX Authentication",
    description="Delete an authentication entity",
)
async def delete_auth(
    client_name: str,
    auth: Annotated[AuthContext, Depends(require_auth_write)],
    ceph: Annotated[CephClient, Depends(get_ceph_client)],
) -> Response:
    """Delete an authentication entity.

    Args:
        client_name: Client name (with or without 'client.' prefix)
        user: Authenticated user info
        ceph: CephClient instance

    Returns:
        Empty response with 204 status

    Raises:
        HTTPException: If client not found or deletion fails
    """
    # Normalize entity name
    entity = client_name if client_name.startswith("client.") else f"client.{client_name}"

    try:
        # First check if entity exists
        exists = await check_auth_exists_internal(ceph, entity)
        if not exists:
            audit_logger.log_operation(
                operation="DELETE",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Not found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=APIResponse.error(
                    code="AUTH_NOT_FOUND",
                    message=f"Authentication entity not found: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        # Execute delete command
        await ceph.execute(["auth", "del", entity])

        audit_logger.log_operation(
            operation="DELETE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="SUCCESS",
        )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except CephCommandError as e:
        # Check if error indicates not found
        if e.status_code == 404 or "not found" in e.message.lower():
            audit_logger.log_operation(
                operation="DELETE",
                resource=f"auth:{entity}",
                user=auth.user,
                status="FAILED",
                details={"error": "Not found"},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=APIResponse.error(
                    code="AUTH_NOT_FOUND",
                    message=f"Authentication entity not found: {entity}",
                    details={"entity": entity},
                ).model_dump(exclude_none=True),
            )

        audit_logger.log_operation(
            operation="DELETE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e), "error_code": e.error_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=APIResponse.error(
                code=e.error_code,
                message=e.message,
                details=e.details,
            ).model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.exception(f"Unexpected error deleting auth: {e}")
        audit_logger.log_operation(
            operation="DELETE",
            resource=f"auth:{entity}",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=APIResponse.error(
                code="INTERNAL_ERROR",
                message="Internal server error",
                details={"error": str(e)},
            ).model_dump(exclude_none=True),
        )


@router.get(
    "/auth",
    response_model=APIResponse,
    summary="List CephX Clients",
    description="List all CephX authentication clients with optional filtering and pagination",
)
async def list_auth(
    filter: Annotated[Union[str, None], Query(description="Prefix filter for client names")] = None,
    limit: Annotated[int, Query(description="Maximum number of results", ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(description="Pagination offset", ge=0)] = 0,
    auth: Annotated[AuthContext, Depends(require_auth_read)] = None,
    ceph: Annotated[CephClient, Depends(get_ceph_client)] = None,
) -> APIResponse:
    """List CephX authentication clients.

    Args:
        filter: Prefix filter for client names
        limit: Maximum number of results
        offset: Pagination offset
        user: Authenticated user info
        ceph: CephClient instance

    Returns:
        APIResponse with paginated list of clients

    Raises:
        HTTPException: If listing fails
    """
    try:
        # Execute list command
        result = await ceph.execute(["auth", "ls", "--format", "json"], format_json=True)

        # Parse result
        if isinstance(result, dict) and "auth_dump" in result:
            auth_list = result["auth_dump"]
        elif isinstance(result, list):
            auth_list = result
        else:
            auth_list = []

        # Filter out system clients and apply user filter
        system_prefixes = ["client.admin", "mgr.", "osd.", "mds.", "mon."]
        filtered_clients = []

        for auth_entry in auth_list:
            entity = auth_entry.get("entity", "")

            # Skip system clients
            if any(entity.startswith(prefix) for prefix in system_prefixes):
                continue

            # Skip non-client entities
            if not entity.startswith("client."):
                continue

            # Apply prefix filter if provided
            if filter:
                client_name = entity[7:] if entity.startswith("client.") else entity
                if not client_name.startswith(filter):
                    continue

            # Create entity object
            try:
                auth_entity = CephXAuthEntity(
                    entity=entity,
                    key=auth_entry.get("key", ""),
                    caps=auth_entry.get("caps", {}),
                )
                filtered_clients.append(auth_entity)
            except Exception as e:
                logger.warning(f"Failed to parse auth entry: {entity} - {e}")
                continue

        # Apply pagination
        total = len(filtered_clients)
        paginated_clients = filtered_clients[offset : offset + limit]

        # Create response
        auth_list_response = CephXAuthList(
            clients=paginated_clients,
            total=total,
            offset=offset,
            limit=limit,
        )

        audit_logger.log_operation(
            operation="LIST",
            resource="auth",
            user=auth.user,
            status="SUCCESS",
            details={"total": total, "filter": filter, "limit": limit, "offset": offset},
        )

        return APIResponse.success(data=auth_list_response.model_dump())

    except CephCommandError as e:
        audit_logger.log_operation(
            operation="LIST",
            resource="auth",
            user=auth.user,
            status="FAILED",
            details={"error": str(e), "error_code": e.error_code},
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=APIResponse.error(
                code=e.error_code,
                message=e.message,
                details=e.details,
            ).model_dump(exclude_none=True),
        )
    except Exception as e:
        logger.exception(f"Unexpected error listing auth: {e}")
        audit_logger.log_operation(
            operation="LIST",
            resource="auth",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=APIResponse.error(
                code="INTERNAL_ERROR",
                message="Internal server error",
                details={"error": str(e)},
            ).model_dump(exclude_none=True),
        )


async def check_auth_exists_internal(ceph: CephClient, entity: str) -> bool:
    """Check if an auth entity exists.

    Args:
        ceph: CephClient instance
        entity: Entity name (with client. prefix)

    Returns:
        True if entity exists, False otherwise
    """
    try:
        result = await ceph.execute(
            ["auth", "get", entity, "--format", "json"],
            format_json=True,
        )
        return bool(result)
    except CephCommandError as e:
        if e.status_code == 404 or "not found" in e.message.lower():
            return False
        raise
