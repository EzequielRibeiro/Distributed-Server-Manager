#!/usr/bin/env bash
# =============================================================
# archive_security.sh
#
# Capivara Distributed Server Manager
#
# Security helpers for validating archive members before
# extraction.
#
# Policy:
# - reject absolute paths;
# - reject path traversal through ".." components;
# - reject unsafe symbolic-link targets;
# - reject unsafe hard-link targets;
# - preserve legitimate special characters in file names;
# - validation must happen before extraction.
#
# This module performs validation only. It does not extract
# archives.
# =============================================================


# -------------------------------------------------------------
# archive_path_is_safe PATH
#
# Returns:
#   0 = safe
#   1 = unsafe
#
# A path is unsafe when:
# - it is empty;
# - it is absolute;
# - one of its slash-separated components is exactly "..".
#
# Components such as:
#   file..txt
#   ..hidden
#   double..dots
#
# are valid.
# -------------------------------------------------------------

archive_path_is_safe()
{
    local path="${1-}"
    local component
    local -a components=()

    if [[ -z "${path}" ]]
    then
        return 1
    fi

    case "${path}" in
        /*)
            return 1
            ;;
    esac

    IFS='/' read -r -a components <<< "${path}"

    for component in "${components[@]}"
    do
        if [[ "${component}" == ".." ]]
        then
            return 1
        fi
    done

    return 0
}


# -------------------------------------------------------------
# archive_link_target_is_safe MEMBER TARGET
#
# Validates the effective destination of a symbolic-link target.
#
# MEMBER is the archive member containing the link.
# TARGET is the link target stored in the archive.
#
# Absolute targets are rejected.
#
# Relative targets are evaluated from the directory containing
# MEMBER. The resulting logical path must never escape above
# the archive root.
# -------------------------------------------------------------

archive_link_target_is_safe()
{
    local member="${1-}"
    local target="${2-}"

    local member_dir
    local combined
    local component
    local depth=0
    local -a components=()

    if ! archive_path_is_safe "${member}"
    then
        return 1
    fi

    if [[ -z "${target}" ]]
    then
        return 1
    fi

    case "${target}" in
        /*)
            return 1
            ;;
    esac

    case "${member}" in
        */*)
            member_dir="${member%/*}"
            ;;
        *)
            member_dir=""
            ;;
    esac

    if [[ -n "${member_dir}" ]]
    then
        combined="${member_dir}/${target}"
    else
        combined="${target}"
    fi

    IFS='/' read -r -a components <<< "${combined}"

    for component in "${components[@]}"
    do
        case "${component}" in
            ""|".")
                ;;

            "..")
                if (( depth == 0 ))
                then
                    return 1
                fi

                ((depth -= 1))
                ;;

            *)
                ((depth += 1))
                ;;
        esac
    done

    return 0
}


# -------------------------------------------------------------
# archive_hardlink_target_is_safe TARGET
#
# GNU tar hard-link targets refer to archive member names rather
# than filesystem paths relative to the hard-link's directory.
#
# Therefore the target follows the same member-name policy:
# no absolute path and no ".." path component.
# -------------------------------------------------------------

archive_hardlink_target_is_safe()
{
    local target="${1-}"

    archive_path_is_safe "${target}"
}


# -------------------------------------------------------------
# archive_validate_member MEMBER
#
# Public helper for validating a regular archive member name.
# -------------------------------------------------------------

archive_validate_member()
{
    local member="${1-}"

    archive_path_is_safe "${member}"
}


# -------------------------------------------------------------
# archive_validate_symlink MEMBER TARGET
#
# Public helper for validating a symbolic-link archive member.
# -------------------------------------------------------------

archive_validate_symlink()
{
    local member="${1-}"
    local target="${2-}"

    archive_path_is_safe "${member}" \
        && archive_link_target_is_safe "${member}" "${target}"
}


# -------------------------------------------------------------
# archive_validate_hardlink MEMBER TARGET
#
# Public helper for validating a hard-link archive member.
# -------------------------------------------------------------

archive_validate_hardlink()
{
    local member="${1-}"
    local target="${2-}"

    archive_path_is_safe "${member}" \
        && archive_hardlink_target_is_safe "${target}"
}

# -------------------------------------------------------------
# archive_release_root_version ROOT
#
# Validates an official Capivara DSM release-package root and
# prints the semantic version encoded in that root.
#
# Accepted root format:
#
#   capivara-dsm-<semver>
#
# Examples:
#
#   capivara-dsm-1.2.3
#   capivara-dsm-1.2.3-rc.1
#   capivara-dsm-1.2.3+build.7
#
# Requires is_semver() to be available in the calling
# environment.
# -------------------------------------------------------------

archive_release_root_version()
{
    local root="${1-}"
    local version

    [[ -n "${root}" ]] || return 1

    case "${root}" in
        capivara-dsm-*)
            version="${root#capivara-dsm-}"
            ;;
        *)
            return 1
            ;;
    esac

    [[ -n "${version}" ]] || return 1

    is_semver "${version}" || return 1

    printf '%s\n' "${version}"
}


# -------------------------------------------------------------
# archive_release_member_root MEMBER
#
# Validates the top-level root of an official Capivara DSM
# release archive member and prints that root.
#
# Every accepted member must belong to a root following:
#
#   capivara-dsm-<semver>
#
# This helper validates the release-root contract. General path
# safety remains the responsibility of the archive path/link
# validation helpers.
# -------------------------------------------------------------

archive_release_member_root()
{
    local member="${1-}"
    local root
    local version

    [[ -n "${member}" ]] || return 1

    case "${member}" in
        /*)
            return 1
            ;;
    esac

    root="${member%%/*}"

    [[ -n "${root}" ]] || return 1
    [[ "${root}" != "." ]] || return 1
    [[ "${root}" != ".." ]] || return 1

    version="$(archive_release_root_version "${root}")" \
        || return 1

    [[ -n "${version}" ]] || return 1

    printf '%s\n' "${root}"
}

# -------------------------------------------------------------
# archive_release_members_root MEMBER...
#
# Validates that all supplied archive members belong to exactly
# one official Capivara DSM release root and prints that root.
#
# Every member must satisfy archive_release_member_root(), and
# every resulting root must be identical.
#
# An empty member list is rejected.
# -------------------------------------------------------------

archive_release_members_root()
{
    local member
    local root
    local expected_root=""

    for member in "$@"
    do
        root="$(archive_release_member_root "${member}")" \
            || return 1

        if [[ -z "${expected_root}" ]]
        then
            expected_root="${root}"
            continue
        fi

        [[ "${root}" == "${expected_root}" ]] \
            || return 1
    done

    [[ -n "${expected_root}" ]] || return 1

    printf '%s\n' "${expected_root}"
}