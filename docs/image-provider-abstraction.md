# Image provider abstraction

The image workflow is bound to model capabilities rather than to SDXL-specific call shapes.

## Profiles

`spec/providers.json` defines immutable image model profiles. A profile owns:

- model family and model id;
- Diffusers text-to-image and image-to-image loaders;
- dtype and optional variant;
- role-specific working resolutions;
- default inference parameters;
- explicit capabilities such as reference images, img2img, inpainting and ControlNet.

The only shipped image profile is `sd35_medium`. Both `local` and `local_sd35` select the local
Stable Diffusion 3.5 Medium model for character, landscape and portrait generation.
There is no implicit fallback between them.

## Runtime isolation

The runtime registry keys image runtimes by profile and resolved model id. Different roles can use
different model families without silently reusing the first Diffusers pipeline. Exclusive accelerator
policy unloads the previous runtime when execution switches to another model.

Requests are checked before inference. An init image requires img2img capability; reference images
require reference-conditioning capability. Unsupported fields fail with a configuration error rather
than being ignored. Model-family loaders receive only their supported options.

## Model catalog

An image catalog entry must declare the supported `model_profile` (`sd35_medium`). A request-scoped
override carries this profile into the adapter binding and adopts the profile's default inference
parameters. The base provider specification remains immutable.

## Operator checks

```powershell
py -3.10 -m ai_story provider-status --mode local --no-probe
py -3.10 -m ai_story provider-status --mode local_sd35 --no-probe
py -3.10 -m ai_story prepare-image-models --mode local
py -3.10 -m ai_story prepare-image-models --mode local_sd35
```

`provider-status` reports capabilities. `prepare-image-models` resolves only dependencies required by
the selected family; SD 3.5 does not download or load the SDXL IP-Adapter.
