{ pkgs ? import <nixpkgs> {} }:
  pkgs.mkShell {
    nativeBuildInputs = with pkgs; [
      mosquitto
      python39
      python39Packages.asyncio-mqtt
      python39Packages.bleak
    ];

    shellHook = ''
       echo "nix shell ready"
    '';
}
