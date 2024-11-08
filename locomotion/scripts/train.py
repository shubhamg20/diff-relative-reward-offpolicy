import sys
sys.path.append('../')
import diffuser.utils as utils
import wandb
import torch
#-----------------------------------------------------------------------------#
#----------------------------------- setup -----------------------------------#
#-----------------------------------------------------------------------------#
def log_gpu_memory(stage):
    print(f"{stage} - Allocated GPU memory: {torch.cuda.memory_allocated() / 1024**2} MB")
    print(f"{stage} - Cached GPU memory: {torch.cuda.memory_reserved() / 1024**2} MB")

class Parser(utils.Parser):
    dataset: str = 'hopper-medium-expert-v2'
    config: str = 'config.locomotion'
    debug: bool = False
    continue_run: bool = False

parser = Parser()
args = parser.parse_args('diffusion', prepare_dirs=False)
# for key, value in vars(args).items():
#     print(f'{key}: {value}')
wandb.init(
    project = "diffusion_relative_rewards", 
    # entity="rrf-diffusion",
    # dir = "/scratch/shared/beegfs/<username>/wandb",
    mode = "online" if not args.debug else "disabled",
    config = args._dict
)

parser.prepare_dirs(args)

assert args.noise_level is None or args.noise_level < 1e-10 or "noised" in args.prefix, "Need to change savepath when using noised dataset"

#-----------------------------------------------------------------------------#
#---------------------------------- dataset ----------------------------------#
#-----------------------------------------------------------------------------#
print(args.savepath)
if not args.continue_run:
    dataset_config = utils.Config(
        args.loader,
        savepath=(args.savepath, 'dataset_config.pkl'),
        env=args.dataset,
        horizon=args.horizon,
        normalizer=args.normalizer,
        preprocess_fns=args.preprocess_fns,
        use_padding=args.use_padding,
        max_path_length=args.max_path_length,
        noise_seed=args.noise_seed,
        noise_level=args.noise_level,
    )

    render_config = utils.Config(
        args.renderer,
        savepath=(args.savepath, 'render_config.pkl'),
        env=args.dataset,
    )

    dataset = dataset_config()
    renderer = render_config()

    observation_dim = dataset.observation_dim
    action_dim = dataset.action_dim
    # Print the dimensions
    print(f'Observation Dimension: {observation_dim}')
    print(f'Action Dimension: {action_dim}')
    # Check the number of samples in the dataset
    num_samples = len(dataset)
    print(f'Number of samples in the dataset: {num_samples}')

    #-----------------------------------------------------------------------------#
    #------------------------------ model & trainer ------------------------------#
    #-----------------------------------------------------------------------------#

    model_config = utils.Config(
        args.model,
        savepath=(args.savepath, 'model_config.pkl'),
        horizon=args.horizon,
        transition_dim=observation_dim + action_dim,
        cond_dim=observation_dim,
        dim_mults=args.dim_mults,
        attention=args.attention,
        device=args.device,
    )

    diffusion_config = utils.Config(
        args.diffusion,
        savepath=(args.savepath, 'diffusion_config.pkl'),
        horizon=args.horizon,
        observation_dim=observation_dim,
        action_dim=action_dim,
        n_timesteps=args.n_diffusion_steps,
        loss_type=args.loss_type,
        clip_denoised=args.clip_denoised,
        predict_epsilon=args.predict_epsilon,
        ## loss weighting
        action_weight=args.action_weight,
        loss_weights=args.loss_weights,
        loss_discount=args.loss_discount,
        device=args.device,
    )

    trainer_config = utils.Config(
        utils.Trainer,
        savepath=(args.savepath, 'trainer_config.pkl'),
        train_batch_size=args.batch_size,
        train_lr=args.learning_rate,
        gradient_accumulate_every=args.gradient_accumulate_every,
        ema_decay=args.ema_decay,
        sample_freq=args.sample_freq,
        save_freq=int(args.n_train_steps // args.n_saves), #args.save_freq,
        label_freq=int(args.n_train_steps // args.n_saves),
        save_parallel=args.save_parallel,
        results_folder=args.savepath,
        # noise_level=args.noise_level,
        bucket=args.bucket,
        n_reference=args.n_reference,
    )

    #-----------------------------------------------------------------------------#
    #-------------------------------- instantiate --------------------------------#
    #-----------------------------------------------------------------------------#

    model = model_config()

    diffusion = diffusion_config(model)

    trainer = trainer_config(diffusion, dataset, renderer)

else:
    print("Continuing existing run")
    diffusion_experiment = utils.load_diffusion(
        args.savepath,
        epoch="latest", seed=args.seed,
    )
    dataset, renderer, model, diffusion, ema, trainer, epoch = diffusion_experiment



#-----------------------------------------------------------------------------#
#------------------------ test forward & backward pass -----------------------#
#-----------------------------------------------------------------------------#

utils.report_parameters(model)

# After model instantiation
model = model_config()
log_gpu_memory("After model instantiation")

# After a forward pass
print('Testing forward...', end=' ', flush=True)
batch = utils.batchify(dataset[0])
loss, _ = diffusion.loss(*batch)
loss.backward()
log_gpu_memory("After forward pass")

#-----------------------------------------------------------------------------#
#--------------------------------- main loop ---------------------------------#
#-----------------------------------------------------------------------------#

n_epochs = int(args.n_train_steps // args.n_steps_per_epoch)

# for i in range(n_epochs):
#     print(f'Epoch {i} / {n_epochs} | {args.savepath}')
#     trainer.train(n_train_steps=args.n_steps_per_epoch)

