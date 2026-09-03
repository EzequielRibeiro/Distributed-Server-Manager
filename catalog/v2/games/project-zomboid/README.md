# Project Zomboid runtime notes

Project Zomboid uses Steam AppID `380870` for the dedicated server runtime and Steam Workshop AppID `108600` for game content.

The generic `steam-workshop` provider remains responsible only for acquisition. Activation is handled by `installer/content_adapters/project-zomboid.sh`, which projects selected content into the canonical server configuration properties:

- `WorkshopItems=<PublishedFileId;...>`
- `Mods=<ModId;...>`

Each Project Zomboid `ContentDefinition` that uses the adapter must provide:

- `artifact.workshop_app_id=108600`;
- a numeric `artifact.published_file_id`;
- `activation.adapter=project-zomboid`;
- `activation.identifier` containing the Project Zomboid Mod ID.

The adapter rejects cross-game Workshop AppIDs, invalid PublishedFileIds, empty Mod IDs, and Mod IDs containing semicolons or line breaks. It deliberately does not download Workshop content and does not add game-specific behavior to the Agent lifecycle.
