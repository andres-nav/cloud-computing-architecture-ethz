{
  description = "Development environment for Cloud Computing Architecture ETH project";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    systems.url = "github:nix-systems/default";
  };

  outputs = { self, nixpkgs, systems }:
    let
      eachSystem = nixpkgs.lib.genAttrs (import systems);
    in
    {
      devShells = eachSystem (system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnsupportedSystem = true;
          };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              kubernetes
              kops
              google-cloud-sdk
              python3
            ];
          };
        });
    };
}
