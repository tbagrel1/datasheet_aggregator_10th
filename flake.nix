{
  description = "Application packaged using poetry2nix";

  inputs.flake-utils.url = "github:numtide/flake-utils";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-23.05";
  inputs.poetry2nix = {
    url = "github:nix-community/poetry2nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        # see https://github.com/nix-community/poetry2nix/tree/master#api for more functions and examples.
        inherit (poetry2nix.legacyPackages.${system}) mkPoetryApplication;
        pkgs = nixpkgs.legacyPackages.${system};
        selectedPython = pkgs.python310Full;
        pythonEnv = poetry2nix.legacyPackages.${system}.mkPoetryEnv {
          python = selectedPython;
          projectDir = ./.;
          # editablePackageSources = { datasheet_aggregator = ./src; };
        };
      in
      {
        packages = {
          datasheet_aggregator = mkPoetryApplication { python = selectedPython; projectDir = ./.; src = ./src; };
          default = self.packages.${system}.datasheet_aggregator;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
          ];
          packages = [
            poetry2nix.packages.${system}.poetry
            pkgs.tk
          ];
        };
      });
}
