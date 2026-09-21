from core.minecraft_content_resolver import resolve_modrinth


def test_modrinth_plugin_accepts_mod_project_with_plugin_loader_version():
    def requester(url, headers):
        if "/project/luckperms/version" in url:
            return [
                {
                    "id": "b0mk8uS6",
                    "project_id": "Vebnzrzj",
                    "version_number": "v5.5.71-bukkit",
                    "version_type": "release",
                    "date_published": "2026-01-01T00:00:00Z",
                    "status": "listed",
                    "game_versions": ["1.21.1"],
                    "loaders": ["bukkit", "paper", "spigot"],
                    "dependencies": [],
                    "files": [
                        {
                            "primary": True,
                            "filename": "LuckPerms-Bukkit-5.5.71.jar",
                            "url": "https://cdn.modrinth.com/data/example/file.jar",
                            "size": 12345,
                            "hashes": {
                                "sha512": "a" * 128,
                                "sha1": "b" * 40,
                            },
                        }
                    ],
                }
            ]

        if "/project/luckperms" in url:
            return {
                "id": "Vebnzrzj",
                "slug": "luckperms",
                "title": "LuckPerms",
                "project_type": "mod",
                "all_project_types": None,
                "categories": ["management", "utility"],
                "additional_categories": [],
                "status": "approved",
            }

        raise AssertionError(f"unexpected URL: {url}")

    result = resolve_modrinth(
        "luckperms",
        "1.21.1",
        ("paper", "bukkit", "spigot"),
        content_type="plugin",
        requester=requester,
    )

    assert result["provider"] == "modrinth"
    assert result["version"] == "v5.5.71-bukkit"
    assert result["artifact"]["filename"] == "LuckPerms-Bukkit-5.5.71.jar"
    assert "paper" in result["provenance"]["loaders"]


def test_modrinth_plugin_rejects_mod_project_without_plugin_compatible_version():
    from core.minecraft_content_resolver import MinecraftContentResolverError
    import pytest

    def requester(url, headers):
        if "/project/example/version" in url:
            return []

        if "/project/example" in url:
            return {
                "id": "example-id",
                "slug": "example",
                "title": "Example Mod",
                "project_type": "mod",
                "categories": ["technology"],
                "status": "approved",
            }

        raise AssertionError(f"unexpected URL: {url}")

    with pytest.raises(
        MinecraftContentResolverError,
        match="no compatible Modrinth version",
    ):
        resolve_modrinth(
            "example",
            "1.21.1",
            ("paper", "bukkit", "spigot"),
            content_type="plugin",
            requester=requester,
        )
