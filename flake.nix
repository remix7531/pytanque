{
  description = "pytanque — Python client for Petanque (coq-lsp)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = {
    self,
    nixpkgs,
    flake-utils,
  }:
    flake-utils.lib.eachDefaultSystem (system: let
      pkgs = import nixpkgs {inherit system;};
      lib = pkgs.lib;
      pyproject = lib.importTOML ./pyproject.toml;
      version = pyproject.project.version;
      python = pkgs.python3;

      pytanque = python.pkgs.buildPythonPackage {
        pname = "pytanque";
        inherit version;
        pyproject = true;

        src = ./.;

        build-system = [python.pkgs.setuptools];

        propagatedBuildInputs = with python.pkgs; [
          typing-extensions
          requests
        ];

        nativeCheckInputs = [python.pkgs.pytestCheckHook];

        pythonImportsCheck = ["pytanque"];

        meta = {
          description = "Python client for the petanque JSON-RPC interface to coq-lsp";
          license = lib.licenses.asl20;
        };
      };
    in {
      packages = {
        inherit pytanque;
        default = pytanque;
      };

      devShells.default = pkgs.mkShell {
        packages = [
          (python.withPackages (ps:
            with ps; [
              typing-extensions
              requests
              pytest
            ]))
        ];
      };
    })
    // {
      overlays.default = final: prev: {
        python3 = prev.python3.override (old: {
          packageOverrides = prev.lib.composeExtensions (old.packageOverrides or (_: _: {})) (pyfinal: pyprev: {
            pytanque = pyfinal.callPackage ({
              lib,
              buildPythonPackage,
              setuptools,
              typing-extensions,
              requests,
            }: let
              pyproject = lib.importTOML ./pyproject.toml;
            in
              buildPythonPackage {
                pname = "pytanque";
                version = pyproject.project.version;
                pyproject = true;
                src = ./.;
                build-system = [setuptools];
                propagatedBuildInputs = [typing-extensions requests];
                pythonImportsCheck = ["pytanque"];
                meta = {
                  description = "Python client for the petanque JSON-RPC interface to coq-lsp";
                  license = lib.licenses.asl20;
                };
              }) {};
          });
        });
      };
    };
}
